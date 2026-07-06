"""
End-to-end NEBNext Ultra II DNA library prep with UMI, closed-loop on a STAR.

    fragmented DNA (50 uL/well, already in the working plate)
      1  End Prep         add buffer + enzyme, ODTC 20C 30m / 65C 30m     (thermal.incubate_tc)
      2  Adaptor Ligation add UMI adaptor + ligation MM + enhancer, 20C 15m, lid off
      3  Cleanup / Size   SPRI on the magnet, elute in 0.1X TE            (common.spri_cleanup)
      4  Indexing PCR     add UDI primer mix + Q5 MM, ODTC cycling        (odtc.run_pcr)
      5  PCR Cleanup      0.8X SPRI, elute in 0.1X TE
      6  QC (closed loop) Tecan dsDNA quant + pass/dilute/fail gate       (qc.run)
      7  TapeStation      manual size-QC handoff, then a measured pool plan

Reuses the shared STAR deck, the ODTC and Tecan backends, and the SPRI/QC steps.
Runs in simulation (chatterbox) and in a no-PyLabRobot dry mode like the rest of
the repo. The loop closes at step 6: the plate-reader concentration of every
well gates pass/dilute/fail and sets the per-well volume that pools passing
libraries to a uniform mass. TapeStation size QC has no automated interface yet,
so on hardware it raises TapeStationHandoffRequired for an operator to run it and
call resume_after_tapestation(); in simulation it is logged and skipped.
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
from .config import Ultra2Config, adaptor_dilution

logger = logging.getLogger("tipseq.ultra2_umi")


class TapeStationHandoffRequired(Exception):
    """Raised on hardware after QC so an operator runs TapeStation size QC."""


@dataclass
class Ultra2DnaUmi:
    cfg: Ultra2Config

    def __post_init__(self):
        self.deckmap = build_deck(self.cfg.num_samples)
        self.registry = ReagentRegistry.build()
        self.devices = build_devices(_as_run_config(self.cfg), self.deckmap)
        self.vision = build_vision(
            self.cfg.vision_enabled, fault_at=self.cfg.vision_fault_at,
            abort_on_fault=self.cfg.vision_abort_on_fault, simulate=self.cfg.simulate)
        self.ops = LiquidOps(self.devices, self.deckmap, self.registry, self.cfg,
                             vision=self.vision)
        # fragmented DNA is already loaded in the working plate at input volume
        for c in range(self.ops.ncols):
            self.ops.well_volume_ul[c] = self.cfg.endprep.dna_ul

    # -- 1. End Prep ---------------------------------------------------------
    async def _end_prep(self):
        ep = self.cfg.endprep
        logger.info("== 1. End Prep (buffer %.0f + enzyme %.0f -> %.0f uL) ==",
                    ep.buffer_ul, ep.enzyme_ul, ep.total_ul)
        await self.ops.add_reagent(C.ULTRA2_END_PREP_BUFFER, ep.buffer_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.ULTRA2_END_PREP_ENZYME, ep.enzyme_ul, mix=True,
                                   new_tips_each_column=True)
        await thermal.incubate_tc(self.ops, [
            ProfileStep(ep.step1_c, ep.step1_s, "endprep-20C"),
            ProfileStep(ep.step2_c, ep.step2_s, "endprep-65C"),
        ], lid_celsius=ep.lid_c, block_max_volume=ep.total_ul)

    # -- 2. Adaptor Ligation -------------------------------------------------
    async def _ligation(self):
        lg = self.cfg.ligation
        dil, conc = adaptor_dilution(self.cfg.input_ng)
        logger.info("== 2. Adaptor Ligation (UMI adaptor %s dilution, %.1f uM working) ==", dil, conc)
        await self.ops.add_reagent(C.UMI_ADAPTOR, lg.umi_adaptor_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.ULTRA2_LIGATION_MM, lg.ligation_mm_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.ULTRA2_LIGATION_ENHANCER, lg.ligation_enhancer_ul,
                                   new_tips_each_column=True)
        # ligation master mix is very viscous: mix thoroughly or ligation efficiency drops
        for c in range(self.ops.ncols):
            await self.ops._mix(c, min(self.ops.well_volume_ul[c] * 0.6, 80.0), cycles=lg.mix_cycles)
        await thermal.incubate_tc(
            self.ops, [ProfileStep(lg.incubation_c, lg.incubation_s, "ligation-20C")],
            lid_celsius=0.0 if lg.lid_off else 105.0, block_max_volume=lg.total_ul)

    # -- 3. Cleanup or size selection ---------------------------------------
    async def _cleanup_or_size_select(self):
        if self.cfg.size_select:
            await self._size_select()
            return
        cl = self.cfg.cleanup
        logger.info("== 3. Cleanup without size selection (%.2fX SPRI, elute %.0f uL 0.1X TE) ==",
                    cl.spri_ratio, cl.elution_ul)
        await self.ops.spri_cleanup(ratio=cl.spri_ratio, elution_ul=cl.elution_ul,
                                    elution_reagent=C.TE_0_1X, ethanol_washes=cl.etoh_washes,
                                    etoh_ul=cl.etoh_ul)
        for c in range(self.ops.ncols):
            self.ops.well_volume_ul[c] = cl.transfer_ul

    async def _size_select(self):
        ss = self.cfg.sizeselect
        first, second = ss.bead_table.get(ss.insert_bp, (40.0, 20.0))
        logger.info("== 3. Two-sided size selection for ~%d bp insert (%.0f then %.0f uL beads) ==",
                    ss.insert_bp, first, second)
        # first bead addition binds LARGE fragments; keep the supernatant
        await self.ops.add_reagent(C.SPRI_BEADS, first, mix=True, new_tips_each_column=True)
        await _sleep(self.cfg.timings.bead_bind, self.cfg)
        await self.devices.magnet.engage(self.ops.lh, self.ops.plate, settle_s=180)
        await self._carry_supernatant_to(self.deckmap.index_plate)
        await self.devices.magnet.disengage(self.ops.lh, self.ops.plate, to_site=self.deckmap.hhs_site)
        self.ops.plate = self.deckmap.index_plate            # library now lives on the second plate
        # second bead addition binds the LIBRARY; keep the beads
        await self.ops.add_reagent(C.SPRI_BEADS, second, mix=True, new_tips_each_column=True)
        await _sleep(self.cfg.timings.bead_bind, self.cfg)
        await self.devices.magnet.engage(self.ops.lh, self.ops.plate, settle_s=180)
        if self.vision:
            await self.vision.check(V.CHECK_BEAD_PELLET, step="size_select_bind")
        await self.ops.remove_supernatant()
        for _ in range(ss.etoh_washes):
            await self.ops.add_reagent(C.ETHANOL_80, ss.etoh_ul, new_tips_each_column=True)
            await _sleep(30, self.cfg)
            await self.ops.remove_supernatant(volume_ul=ss.etoh_ul)
        await _sleep(self.cfg.timings.bead_dry, self.cfg)
        await self.devices.magnet.disengage(self.ops.lh, self.ops.plate, to_site=self.deckmap.hhs_site)
        await self.ops.add_reagent(C.TE_0_1X, ss.elution_ul, mix=True, new_tips_each_column=True)
        await self.devices.magnet.engage(self.ops.lh, self.ops.plate, settle_s=120)
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
        logger.info("== 4. Indexing PCR (%d cycles for %.0f ng input) ==", n, self.cfg.input_ng)
        await self.ops.add_reagent(C.NEBNEXT_UDI_PRIMERS, p.primer_mix_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.ULTRA2_Q5_MM, p.q5_mm_ul, mix=True, new_tips_each_column=True)
        await self.ops.to_thermocycler()
        await self.devices.tc.open_lid()
        await self.devices.tc.run_pcr(
            gapfill=None,
            initial_denature=ProfileStep(*p.initial_denature, name="initial-denature"),
            denature=ProfileStep(*p.denature, name="denature"),
            anneal_extend=ProfileStep(*p.anneal_extend, name="anneal-extend"),
            cycles=n,
            final_extend=ProfileStep(*p.final_extend, name="final-extend"),
            hold_celsius=p.hold_c,
            block_max_volume=p.total_ul,
            lid_celsius=p.lid_c,
        )

    # -- 5. PCR cleanup ------------------------------------------------------
    async def _pcr_cleanup(self):
        pc = self.cfg.pcr_cleanup
        logger.info("== 5. PCR Cleanup (%.2fX SPRI, elute %.0f uL 0.1X TE) ==", pc.spri_ratio, pc.elution_ul)
        await self.ops.spri_cleanup(ratio=pc.spri_ratio, elution_ul=pc.elution_ul,
                                    elution_reagent=C.TE_0_1X, ethanol_washes=pc.etoh_washes,
                                    etoh_ul=pc.etoh_ul)
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
        target_mass = self.cfg.pool_target_ng_per_ul * self.cfg.pool_final_ul   # ng per well into the pool
        plan = []
        for w in wells:
            if w["verdict"] == "fail":
                plan.append({"well": w["well"], "action": "exclude", "sample_ul": 0.0, "water_ul": 0.0})
                continue
            conc = max(w["ng_per_ul"], 1e-6)
            take = min(target_mass / conc, self.cfg.pool_final_ul)
            plan.append({
                "well": w["well"], "action": "pool",
                "sample_ul": round(take, 2),
                "water_ul": round(max(self.cfg.pool_final_ul - take, 0.0), 2),
            })
        return plan

    # -- run -----------------------------------------------------------------
    async def run(self) -> dict:
        from ...validation import PROTOCOL_STATUS
        logger.info("### NEBNext Ultra II DNA + UMI start: %d samples, %.0f ng input, simulate=%s",
                    self.cfg.num_samples, self.cfg.input_ng, self.cfg.simulate)
        await self.devices.setup()
        report: dict = {"status": "complete"}
        try:
            try:
                await self._end_prep()
                await self._ligation()
                await self._cleanup_or_size_select()
                await self._pcr()
                await self._pcr_cleanup()
                report.update(await self._qc_and_pool())
                tier = PROTOCOL_STATUS.get("dna_ultra2_umi", {}).get("tier")
                report["validation_tier"] = tier.value if tier is not None else "untested"
                report["pcr_cycles"] = self.cfg.cycles()
                await self._tapestation_handoff(report)
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

    async def _tapestation_handoff(self, report: dict):
        msg = ("TapeStation size QC is manual for now: run an Agilent HS D1000 assay on "
               "the finished libraries to confirm insert size before pooling.")
        if self.cfg.simulate:
            logger.warning("[sim] %s Continuing (no automated TapeStation interface).", msg)
            report["tapestation"] = "manual (simulated: skipped)"
            return
        report["tapestation"] = "manual (operator handoff)"
        raise TapeStationHandoffRequired(msg + " Then call resume_after_tapestation(report).")

    async def resume_after_tapestation(self, report: dict) -> dict:
        """Entry point once an operator has run and cleared the manual TapeStation."""
        report["tapestation"] = "manual (operator confirmed)"
        report["resumed"] = True
        logger.info("### resumed after TapeStation: libraries cleared for pooling")
        return report


def _as_run_config(cfg: Ultra2Config):
    """Adapt Ultra2Config to the RunConfig fields build_devices reads."""
    from ...config import RunConfig, Method
    rc = RunConfig(method=Method.CUT_AND_TAG, num_samples=cfg.num_samples,
                   simulate=cfg.simulate, odtc_host=cfg.odtc_host, odtc_port=cfg.odtc_port,
                   tecan_host=cfg.tecan_host, star_id=cfg.star_id)
    setattr(rc, "_sim_time_scale", getattr(cfg, "_sim_time_scale", 0.0))
    return rc
