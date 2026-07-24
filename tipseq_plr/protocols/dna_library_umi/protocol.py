"""
Generic UMI library-workflow orchestration on a STAR.

The orchestrator supplies control flow only: end preparation, ligation, cleanup
or explicit two-sided selection, PCR, cleanup, QC, and pooling. Every chemistry
number comes from the attached `DnaLibraryMethod`. The repository bundles only
a synthetic method that is rejected for live runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ... import config as C
from ...deck import build_deck
from ...devices import build_devices, _sleep
from ...reagents import ReagentRegistry
from ...steps.common import LiquidOps
from ...steps import thermal, qc
from ...steps import vision as V
from ...steps.vision import build_vision, VisionFault
from ...backends import ProfileStep
from .config import DnaLibraryConfig

logger = logging.getLogger("tipseq.dna_library_umi")


class FragmentAnalysisHandoffRequired(Exception):
    """Raised on hardware after QC so an operator runs fragment-size analysis."""


@dataclass
class DnaLibraryUmi:
    cfg: DnaLibraryConfig

    def __post_init__(self):
        self.deckmap = build_deck(self.cfg.num_samples)
        self.registry = ReagentRegistry.build()
        self.devices = build_devices(_as_run_config(self.cfg), self.deckmap)
        self.vision = build_vision(
            self.cfg.vision_enabled, fault_at=self.cfg.vision_fault_at,
            abort_on_fault=self.cfg.vision_abort_on_fault, simulate=self.cfg.simulate)
        self.ops = LiquidOps(self.devices, self.deckmap, self.registry, self.cfg,
                             vision=self.vision)
        # Input material is already loaded in the working plate at the
        # operator-supplied method volume.
        for c in range(self.ops.ncols):
            self.ops.well_volume_ul[c] = self.cfg.endprep.input_ul

    # -- 1. End Prep ---------------------------------------------------------
    async def _end_repair(self):
        ep = self.cfg.endprep
        logger.info("== 1. End Prep (buffer %.0f + enzyme %.0f -> %.0f uL) ==",
                    ep.buffer_ul, ep.enzyme_ul, ep.total_ul)
        await self.ops.add_reagent(C.END_REPAIR_BUFFER, ep.buffer_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.END_REPAIR_ENZYME, ep.enzyme_ul, mix=True,
                                   new_tips_each_column=True)
        await thermal.incubate_tc(
            self.ops,
            [ProfileStep(step.celsius, step.seconds, step.name) for step in ep.thermal_steps],
            lid_celsius=ep.lid_c,
            block_max_volume=ep.total_ul,
        )

    # -- 2. Adaptor Ligation -------------------------------------------------
    async def _ligation(self):
        lg = self.cfg.ligation
        incoming_ul = self.ops.well_volume_ul[0]
        logger.info("== 2. Adaptor Ligation (%s) ==", lg.adaptor_preparation)
        await self.ops.add_reagent(C.UMI_ADAPTOR, lg.adaptor_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.LIGATION_MASTER_MIX, lg.master_mix_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.LIGATION_ENHANCER, lg.enhancer_ul,
                                   new_tips_each_column=True)
        for c in range(self.ops.ncols):
            await self.ops._pick(c)
            await self.ops._mix(c, min(self.ops.well_volume_ul[c] * 0.6, 80.0), cycles=lg.mix_cycles)
            await self.ops._drop()
        await thermal.incubate_tc(
            self.ops,
            [ProfileStep(lg.incubation.celsius, lg.incubation.seconds, lg.incubation.name)],
            lid_celsius=lg.lid_c,
            block_max_volume=lg.total_ul(incoming_ul),
        )

    # -- 3. Cleanup or size selection ---------------------------------------
    async def _cleanup_or_size_select(self):
        if self.cfg.size_select:
            await self._size_select()
            return
        cl = self.cfg.cleanup
        logger.info("== 3. Cleanup without size selection (%.2fX beads, elute %.0f uL) ==",
                    cl.bead_ratio, cl.elution_ul)
        await self.ops.spri_cleanup(ratio=cl.bead_ratio, elution_ul=cl.elution_ul,
                                    elution_reagent=C.TE_0_1X,
                                    ethanol_washes=cl.ethanol_washes,
                                    etoh_ul=cl.ethanol_ul)
        for c in range(self.ops.ncols):
            self.ops.well_volume_ul[c] = cl.transfer_ul

    async def _size_select(self):
        ss = self.cfg.sizeselect
        if ss is None:
            raise RuntimeError("size-selection method is not configured")
        first, second = ss.first_bead_ul, ss.second_bead_ul
        logger.info("== 3. Explicit two-sided size selection (%.0f then %.0f uL beads) ==",
                    first, second)
        # first bead addition binds LARGE fragments; keep the supernatant
        await self.ops.add_reagent(C.SPRI_BEADS, first, mix=True, new_tips_each_column=True)
        await _sleep(self.cfg.timings.bead_bind, self.cfg)
        await self.devices.magnet.engage(
            self.ops.lh, self.ops.plate, settle_s=ss.first_magnet_settle_s)
        await self._carry_supernatant_to(self.deckmap.index_plate)
        await self.devices.magnet.disengage(self.ops.lh, self.ops.plate, to_site=self.deckmap.hhs_site)
        self.ops.plate = self.deckmap.index_plate            # library now lives on the second plate
        # second bead addition binds the LIBRARY; keep the beads
        await self.ops.add_reagent(C.SPRI_BEADS, second, mix=True, new_tips_each_column=True)
        await _sleep(self.cfg.timings.bead_bind, self.cfg)
        await self.devices.magnet.engage(
            self.ops.lh, self.ops.plate, settle_s=ss.second_magnet_settle_s)
        if self.vision:
            await self.vision.check(V.CHECK_BEAD_PELLET, step="size_select_bind")
        await self.ops.remove_supernatant()
        for _ in range(ss.ethanol_washes):
            await self.ops.add_reagent(
                C.ETHANOL_80, ss.ethanol_ul, new_tips_each_column=True)
            await _sleep(ss.ethanol_soak_s, self.cfg)
            await self.ops.remove_supernatant(volume_ul=ss.ethanol_ul)
        await _sleep(self.cfg.timings.bead_dry, self.cfg)
        await self.devices.magnet.disengage(self.ops.lh, self.ops.plate, to_site=self.deckmap.hhs_site)
        await self.ops.add_reagent(C.TE_0_1X, ss.elution_ul, mix=True, new_tips_each_column=True)
        await self.devices.magnet.engage(
            self.ops.lh, self.ops.plate, settle_s=ss.final_clear_settle_s)
        for c in range(self.ops.ncols):
            self.ops.well_volume_ul[c] = ss.transfer_ul

    async def _carry_supernatant_to(self, dest_plate):
        """Move the small-fragment supernatant into dest_plate, fresh tips/column."""
        for c in range(self.ops.ncols):
            v = max(self.ops.well_volume_ul[c] - 2.0, 0.0)
            if not self.ops.dry:
                await self.ops._pick(c)
                await self.ops.lh.aspirate(self.ops._wells(c), vols=[v] * 8)
                await self.ops.lh.dispense(dest_plate[self.ops._col(c)], vols=[v] * 8)
                await self.ops._drop()
            self.ops.well_volume_ul[c] = v

    # -- 4. Indexing PCR -----------------------------------------------------
    async def _pcr(self):
        p = self.cfg.pcr
        n = self.cfg.cycles()
        incoming_ul = self.ops.well_volume_ul[0]
        logger.info("== 4. Indexing PCR (%d operator-supplied cycles) ==", n)
        await self.ops.add_reagent(C.UDI_PRIMER_MIX, p.primer_mix_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.LIBRARY_PCR_MASTER_MIX, p.master_mix_ul, mix=True, new_tips_each_column=True)
        await self.ops.to_thermocycler()
        await self.devices.tc.open_lid()
        await self.devices.tc.run_pcr(
            gapfill=None,
            initial_denature=ProfileStep(
                p.initial_denature.celsius, p.initial_denature.seconds, p.initial_denature.name),
            denature=ProfileStep(p.denature.celsius, p.denature.seconds, p.denature.name),
            anneal_extend=ProfileStep(
                p.anneal_extend.celsius, p.anneal_extend.seconds, p.anneal_extend.name),
            cycles=n,
            final_extend=ProfileStep(
                p.final_extend.celsius, p.final_extend.seconds, p.final_extend.name),
            hold_celsius=p.hold_c,
            block_max_volume=p.total_ul(incoming_ul),
            lid_celsius=p.lid_c,
        )

    # -- 5. PCR cleanup ------------------------------------------------------
    async def _pcr_cleanup(self):
        pc = self.cfg.pcr_cleanup
        logger.info("== 5. PCR Cleanup (%.2fX beads, elute %.0f uL) ==",
                    pc.bead_ratio, pc.elution_ul)
        await self.ops.spri_cleanup(ratio=pc.bead_ratio, elution_ul=pc.elution_ul,
                                    elution_reagent=C.TE_0_1X,
                                    ethanol_washes=pc.ethanol_washes,
                                    etoh_ul=pc.ethanol_ul)
        for c in range(self.ops.ncols):
            self.ops.well_volume_ul[c] = pc.transfer_ul

    # -- 6. QC + closed-loop pool plan --------------------------------------
    async def _qc_and_pool(self) -> dict:
        logger.info("== 6. Library QC (Tecan dsDNA quant, closed-loop gate) ==")
        report = await qc.run(self.ops)
        report["pool_plan"] = self._pool_plan(report["wells"])
        return report

    def _pool_plan(self, wells) -> list:
        """Close the loop: the measured ng/uL of each well sets a per-well volume
        that pools passing libraries to a uniform mass. Failed wells are excluded;
        wells hot enough get diluted with water to hit the target."""
        pooling = self.cfg.pooling
        target_mass = pooling.target_ng_per_ul * pooling.final_volume_ul
        plan = []
        for w in wells:
            if w["verdict"] == "fail":
                plan.append({"well": w["well"], "action": "exclude", "sample_ul": 0.0, "water_ul": 0.0})
                continue
            conc = max(w["ng_per_ul"], 1e-6)
            take = min(target_mass / conc, pooling.final_volume_ul)
            plan.append({
                "well": w["well"], "action": "pool",
                "sample_ul": round(take, 2),
                "water_ul": round(max(pooling.final_volume_ul - take, 0.0), 2),
            })
        return plan

    # -- run -----------------------------------------------------------------
    async def run(self) -> dict:
        from ...validation import PROTOCOL_STATUS
        logger.info("### Generic UMI library workflow start: %d samples, profile=%s, simulate=%s",
                    self.cfg.num_samples, self.cfg.method.profile_id, self.cfg.simulate)
        await self.devices.setup()
        report: dict = {"status": "complete"}
        try:
            try:
                await self._end_repair()
                await self._ligation()
                await self._cleanup_or_size_select()
                await self._pcr()
                await self._pcr_cleanup()
                report.update(await self._qc_and_pool())
                tier = PROTOCOL_STATUS.get("dna_library_umi", {}).get("tier")
                report["validation_tier"] = tier.value if tier is not None else "untested"
                report["pcr_cycles"] = self.cfg.cycles()
                report["method_profile"] = self.cfg.method.profile_id
                await self._fragment_analysis_handoff(report)
                logger.info("### run complete: %s", report["counts"])
            except VisionFault as vf:
                # in-process CV caught a fault the plate reader could not see, and
                # caught it in time: abort before spending PCR/QC on a dead plate.
                report["status"] = "aborted"
                report["vision_fault"] = str(vf)
                report.setdefault("counts", {"pass": 0, "dilute": 0, "fail": 0})
                report.setdefault("pool_plan", [])
                logger.error("### run aborted by CV checkpoint: %s", vf)
            if self.vision is not None:
                report["vision_log"] = [vars(v) for v in self.vision.log]
                report["vision_faults"] = len(self.vision.faults)
            return report
        finally:
            await self.devices.stop()

    async def _fragment_analysis_handoff(self, report: dict):
        msg = (
            "Fragment-size QC is manual: analyze the finished libraries to confirm "
            "insert size before pooling."
        )
        if self.cfg.simulate:
            logger.warning("[sim] %s Continuing (no automated fragment-analysis interface).", msg)
            report["fragment_analysis"] = "manual (simulated: skipped)"
            return
        report["fragment_analysis"] = "manual (operator handoff)"
        raise FragmentAnalysisHandoffRequired(msg + " Then call resume_after_fragment_analysis(report).")

    async def resume_after_fragment_analysis(self, report: dict) -> dict:
        """Entry point once an operator has cleared the manual fragment-size QC."""
        report["fragment_analysis"] = "manual (operator confirmed)"
        report["resumed"] = True
        logger.info("### resumed after fragment-size QC: libraries cleared for pooling")
        return report


def _as_run_config(cfg: DnaLibraryConfig):
    """Adapt DnaLibraryConfig to the RunConfig fields build_devices reads."""
    from ...config import RunConfig, Method
    rc = RunConfig(method=Method.CUT_AND_TAG, num_samples=cfg.num_samples,
                   simulate=cfg.simulate, odtc_host=cfg.odtc_host, odtc_port=cfg.odtc_port,
                   tecan_host=cfg.tecan_host, star_id=cfg.star_id)
    setattr(rc, "_sim_time_scale", getattr(cfg, "_sim_time_scale", 0.0))
    return rc
