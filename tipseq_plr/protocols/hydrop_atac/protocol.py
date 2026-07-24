"""
HyDrop scATAC library prep, STAR-orchestrated, with an Onyx droplet-generation
step bridged by a PLR-driven robot arm.

Stages:
  1 nuclei prep      lyse -> wash -> resuspend (STAR; pelleting via integrated
                     centrifuge or off-deck spin, flagged)
  2 tagmentation     ATAC reaction mix, 37C 1 h (ODTC/HHS, no shaking)
  3 co-encapsulation STAR assembles the aqueous inlet (tagmented nuclei + linear-
                     amplification PCR mix) and loads the Onyx chip inlets
                     (sample / HyDrop beads / HFE oil)
  ---- ARM: carry the loaded chip STAR -> Onyx ----
  4 droplet gen      Onyx co-encapsulates into a water-in-oil emulsion
  ---- ARM: carry the emulsion Onyx -> ODTC/STAR ----
  5 linear amp       72C 15', 98C 3', 12x(98/63/72), hold 4C (ODTC)
  6 emulsion break   recovery agent + GuSCN + DTT on ice; capture bead capture, wash,
                     elute (STAR + magnet)
  7 cleanup          1x SPRI beads (STAR + magnet)
  8 index PCR        high-fidelity PCR mix + i5/i7 (ODTC)
  9 size select      0.4-1.2x double-sided SPRI beads (STAR + magnet)
 10 QC               Tecan dsDNA quant

The arm handoffs are the whole point: the STAR never touches the Onyx and the
Onyx never touches the deck; the arm moves labware between their nests. Same arm
abstraction reused for the FACSMelody plate handoff.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List

from ...backends import DropletParams, ProfileStep, Site
from ...deck import build_deck
from ...devices import build_devices, _sleep
from ...steps.qc import _least_squares
from .config import HyDropConfig

logger = logging.getLogger("tipseq.hydrop")

_ROWS = "ABCDEFGH"

# Named arm transfer sites (taught once on the physical cell).
SITE_STAR = "star_transfer"
SITE_ONYX_LOAD = "onyx_load"
SITE_ONYX_OUT = "onyx_output"
SITE_ODTC = "odtc_nest"


class _HyDropOps:
    """Lightweight column-wise liquid handling + bead cleanups for HyDrop.
    Dry-aware: logs intent when PyLabRobot is absent, real calls otherwise."""

    def __init__(self, devices, deckmap, cfg: HyDropConfig, rc):
        self.dev = devices
        self.lh = devices.lh
        self.dm = deckmap
        self.cfg = cfg
        self.rc = rc
        self.dry = self.lh is None
        self.ncols = math.ceil(cfg.num_samples / 8)

    def _col(self, c):
        return f"A{c + 1}:H{c + 1}"

    @staticmethod
    def _eight_channels(resource):
        """Expand a shared reagent well across the STAR's eight channels."""
        if isinstance(resource, (list, tuple)):
            if len(resource) == 1:
                return [resource[0]] * 8
            if len(resource) != 8:
                raise ValueError(f"Expected one or eight channel resources, got {len(resource)}")
            return resource
        return [resource] * 8

    async def add(self, reagent: str, vol: float, *, new_tips=True):
        logger.info("add %-28s %6.1f uL x %d col", reagent, vol, self.ncols)
        if self.dry:
            return
        # Reagents are drawn from the shared reagent carrier reservoirs; for a
        # real run map each HyDrop reagent to a reservoir column here.
        # Use a full reservoir column: one source well per STAR channel.
        src = self.dm.reagent_troughs[0]["A1:H1"]
        for c in range(self.ncols):
            await self.lh.pick_up_tips(self.dm.tips_50[self._col(c)])
            await self.lh.aspirate(self._eight_channels(src), vols=[vol] * 8)
            await self.lh.dispense(self.dm.working_plate[self._col(c)], vols=[vol] * 8)
            await self.lh.discard_tips()

    async def remove_supernatant(self, vol: float):
        logger.info("remove supernatant %.1f uL", vol)
        if self.dry:
            return
        for c in range(self.ncols):
            await self.lh.pick_up_tips(self.dm.tips_50[self._col(c)])
            await self.lh.aspirate(self.dm.working_plate[self._col(c)], vols=[max(vol - 2, 0)] * 8)
            await self.lh.discard_tips()

    async def bead_cleanup(self, bead_reagent: str, *, add_beads_ul: float,
                           elution_reagent: str, elution_ul: float, washes: int = 2,
                           etoh_ul: float = 100.0):
        """Generic magnetic-bead cleanup (capture beads or SPRI beads)."""
        cfg = self.cfg
        await self.add(bead_reagent, add_beads_ul)
        await _sleep(cfg.timings.capture_bead_bind_s, self.rc)
        await self.dev.magnet.engage(self.lh, self.dm.working_plate, settle_s=120)
        await self.remove_supernatant(add_beads_ul + 60)
        for _ in range(washes):
            await self.add("ethanol_80", etoh_ul)
            await _sleep(30, self.rc)
            await self.remove_supernatant(etoh_ul)
        await _sleep(cfg.timings.bead_dry_s, self.rc)
        await self.dev.magnet.disengage(self.lh, self.dm.working_plate)
        await self.add(elution_reagent, elution_ul)


@dataclass
class HyDropATAC:
    cfg: HyDropConfig

    def __post_init__(self):
        self.deckmap = build_deck(self.cfg.num_samples)
        self.rc = _as_run_config(self.cfg)
        self.devices = build_devices(self.rc, self.deckmap)
        self.ops = _HyDropOps(self.devices, self.deckmap, self.cfg, self.rc)
        self._teach_arm_sites()

    def _teach_arm_sites(self):
        if self.devices.arm is None:
            return
        for name, inst in ((SITE_STAR, "star"), (SITE_ONYX_LOAD, "onyx"),
                           (SITE_ONYX_OUT, "onyx"), (SITE_ODTC, "odtc")):
            self.devices.arm.register_site(Site(name=name, instrument=inst))

    # -- stages --------------------------------------------------------------
    async def nuclei_prep(self):
        from . import config as H
        cfg = self.cfg
        logger.info("== nuclei prep (lyse -> wash -> resuspend) ==")
        await self.ops.add(H.ATAC_LYSIS, cfg.volumes.lysis_ul)
        await _sleep(cfg.timings.lysis_s, self.rc)          # 5 min on ice
        if cfg.nuclei_preconcentrated:
            logger.info("nuclei pre-concentrated; skipping wash/spin")
        else:
            await self.ops.add(H.ATAC_WASH, cfg.volumes.wash_ul)
            await self._spin(cfg.spin_rcf_g, cfg.spin_seconds, cfg.spin_temperature_c)
            await self.ops.remove_supernatant(cfg.volumes.wash_ul)
        await self.ops.add(H.PBS, cfg.volumes.pbs_resuspend_ul)
        logger.info("filter 40 um strainer (manual or integrated) before tagmentation")

    async def _spin(self, rcf_g: float, seconds: int, temp_c: float):
        """Pellet nuclei. Deck-integrated VSpin loads via the STAR gripper; if no
        centrifuge is configured, fall back to an off-deck spin note."""
        cf = self.devices.centrifuge
        if cf is None:
            logger.info("centrifuge %.0fg %ds %.0fC (off-deck spin; or enable VSpin)",
                        rcf_g, seconds, temp_c)
            return
        # STAR iSWAP loads the plate into the VSpin; balance with a counterweight.
        cf.declare_balanced(True)
        await cf.spin(rcf_g, seconds, temperature_c=temp_c)

    async def tagmentation(self):
        from . import config as H
        cfg = self.cfg
        logger.info("== tagmentation (ATAC reaction mix, 37C 1 h) ==")
        await self.ops.add(H.ATAC_RXN_MIX, cfg.volumes.reaction_mix_ul)
        # no shaking: ODTC block hold at 37C
        await self._odtc([ProfileStep(cfg.temps.tagmentation, cfg.timings.tagmentation_s,
                                      "tagment")], lid_c=45.0)

    async def co_encapsulation(self):
        from . import config as H
        cfg = self.cfg
        logger.info("== assemble co-encapsulation + load Onyx inlets ==")
        # aqueous inlet: tagmented nuclei + linear-amplification PCR mix
        await self.ops.add(H.LINAMP_PCR_MIX, cfg.volumes.linamp_pcr_ul)
        # load the three Onyx inlets on the chip (STAR pipettes into chip wells)
        logger.info("load Onyx chip: sample(aqueous), beads %.0f uL, HFE oil",
                    cfg.volumes.beads_ul)
        await self.ops.add(H.HYDROP_BEADS, cfg.volumes.beads_ul)   # into bead inlet
        await self.ops.add(H.HFE_OIL, 200.0)                       # into oil inlet

    async def droplet_generation(self) -> float:
        cfg = self.cfg
        arm, onyx = self.devices.arm, self.devices.onyx
        logger.info("== droplet generation on Onyx (arm-bridged) ==")
        if arm is not None:
            await arm.transfer("onyx_chip", SITE_STAR, SITE_ONYX_LOAD)
        if onyx is None:
            logger.warning("no Onyx configured; simulating emulsion collection")
            vol = cfg.volumes.emulsion_target_ul
        else:
            vol = await onyx.run_hydrop(DropletParams(
                sample_pressure_mbar=cfg.sample_pressure_mbar,
                bead_pressure_mbar=cfg.bead_pressure_mbar,
                oil_pressure_mbar=cfg.oil_pressure_mbar,
                target_emulsion_ul=cfg.volumes.emulsion_target_ul,
            ))
        if arm is not None:
            await arm.transfer("emulsion_plate", SITE_ONYX_OUT, SITE_ODTC)
        logger.info("collected %.0f uL emulsion, staged at ODTC", vol)
        return vol

    async def linear_amplification(self):
        cfg = self.cfg
        p = cfg.linamp
        logger.info("== linear amplification (in-emulsion, ODTC) ==")
        steps = [
            ProfileStep(p.gapfill_c, p.gapfill_s, "gapfill"),
            ProfileStep(p.initial_denature_c, p.initial_denature_s, "init-denat"),
        ]
        for _ in range(p.cycles):
            steps.append(ProfileStep(p.denature_c, p.denature_s, "denat"))
            steps.append(ProfileStep(p.anneal_c, p.anneal_s, "anneal"))
            steps.append(ProfileStep(p.extend_c, p.extend_s, "extend"))
        await self._odtc(steps, lid_c=105.0)

    async def emulsion_break(self):
        from . import config as H
        cfg = self.cfg
        logger.info("== emulsion break + capture bead capture ==")
        for reagent, vol in ((H.RECOVERY_AGENT, cfg.volumes.recovery_agent_ul),
                             (H.GUSCN_BUFFER, cfg.volumes.guscn_ul),
                             (H.DTT_1M, cfg.volumes.dtt_ul)):
            await self.ops.add(reagent, vol)
        await _sleep(cfg.timings.emulsion_break_ice_s, self.rc)
        await self.ops.bead_cleanup(
            H.CAPTURE_BEADS, add_beads_ul=cfg.volumes.capture_beads_ul,
            elution_reagent=H.ELUTION_BUFFER, elution_ul=cfg.volumes.capture_bead_elution_ul,
            washes=2, etoh_ul=cfg.volumes.etoh_ul)

    async def spri_cleanup(self):
        from . import config as H
        cfg = self.cfg
        logger.info("== 1x SPRI beads cleanup ==")
        await self.ops.bead_cleanup(
            H.SPRI_BEADS, add_beads_ul=cfg.volumes.capture_bead_elution_ul * cfg.volumes.spri_ratio_1,
            elution_reagent=H.ELUTION_BUFFER, elution_ul=cfg.volumes.spri_elution_ul,
            washes=2, etoh_ul=cfg.volumes.etoh_ul)

    async def index_pcr(self):
        from . import config as H
        cfg = self.cfg
        p = cfg.index_pcr
        logger.info("== index PCR (high-fidelity PCR mix + i5/i7, %d cycles) ==", p.cycles)
        await self.ops.add(H.HIGH_FIDELITY_PCR_MIX, cfg.volumes.index_pcr_ul - cfg.volumes.spri_elution_ul
                           - cfg.volumes.index_i5_ul - cfg.volumes.index_i7_ul)
        await self.ops.add(H.INDEX_I5, cfg.volumes.index_i5_ul)
        await self.ops.add(H.INDEX_I7, cfg.volumes.index_i7_ul)
        steps = []
        for _ in range(p.cycles):
            steps.append(ProfileStep(p.denature_c, p.denature_s, "denat"))
            steps.append(ProfileStep(p.anneal_c, p.anneal_s, "anneal"))
            steps.append(ProfileStep(p.extend_c, p.extend_s, "extend"))
        await self._odtc(steps, lid_c=105.0)

    async def size_selection(self):
        from . import config as H
        cfg = self.cfg
        logger.info("== double-sided size selection (%.1f-%.1fx) ==",
                    cfg.volumes.sizeselect_low, cfg.volumes.sizeselect_high)
        await self.ops.bead_cleanup(
            H.SPRI_BEADS, add_beads_ul=cfg.volumes.index_pcr_ul * cfg.volumes.sizeselect_high,
            elution_reagent=H.ELUTION_BUFFER, elution_ul=cfg.volumes.final_elution_ul,
            washes=2, etoh_ul=cfg.volumes.etoh_ul)

    async def qc(self) -> dict:
        cfg = self.cfg
        logger.info("== QC (Tecan dsDNA quant) ==")
        grid = await self.devices.reader.read_fluorescence(excitation_wavelength=485,
                                                           emission_wavelength=530)
        std = [(ng, 50 + ng * 800) for ng in (0.0, 0.1, 0.5, 1.0, 5.0, 10.0)]
        m, b = _least_squares([r for _, r in std], [ng for ng, _ in std])
        concs = {}
        for c in range(self.ops.ncols):
            for r in range(8):
                if c * 8 + r >= cfg.num_samples:
                    continue
                concs[f"{_ROWS[r]}{c + 1}"] = max(m * grid[r][c] + b, 0.0)
        passed = sum(1 for v in concs.values() if v >= 0.2)
        logger.info("QC: %d/%d libraries above 0.2 ng/uL", passed, len(concs))
        return {"libraries": len(concs), "pass": passed,
                "concentrations": {k: round(v, 3) for k, v in concs.items()}}

    # -- run -----------------------------------------------------------------
    async def run(self) -> dict:
        cfg = self.cfg
        logger.info("### HyDrop scATAC start: %d samples (%d nuclei -> ~%d cells each)",
                    cfg.num_samples, cfg.nuclei_per_reaction, cfg.target_cells)
        await self.devices.setup()
        try:
            await self.nuclei_prep()
            await self.tagmentation()
            await self.co_encapsulation()
            emulsion_ul = await self.droplet_generation()
            await self.linear_amplification()
            await self.emulsion_break()
            await self.spri_cleanup()
            await self.index_pcr()
            await self.size_selection()
            report = await self.qc()
            report["samples"] = cfg.num_samples
            report["emulsion_ul"] = emulsion_ul
            logger.info("### HyDrop run complete")
            return report
        finally:
            await self.devices.stop()

    # -- helpers -------------------------------------------------------------
    async def _odtc(self, steps: List[ProfileStep], lid_c: float):
        # stage plate at ODTC (arm or STAR gripper) then run
        await self.devices.tc.open_lid()
        await self.devices.tc.run_profile(steps, block_max_volume=50.0, lid_celsius=lid_c)


def _as_run_config(cfg: HyDropConfig):
    from ...config import RunConfig, Method
    rc = RunConfig(method=Method.PLATE_TIPSEQ, num_samples=cfg.num_samples,
                   simulate=cfg.simulate, odtc_host=cfg.odtc_host, odtc_port=cfg.odtc_port,
                   tecan_host=cfg.tecan_host)
    setattr(rc, "_sim_time_scale", getattr(cfg, "_sim_time_scale", 0.0))
    # enable the arm + Onyx for this workflow
    setattr(rc, "arm_enabled", True)
    setattr(rc, "arm_kind", cfg.arm_kind)
    setattr(rc, "arm_host", cfg.arm_host)
    setattr(rc, "arm_motion_enabled", False)   # sim-safe; True only on a taught cell
    setattr(rc, "onyx_enabled", True)
    setattr(rc, "onyx_host", cfg.onyx_host)
    setattr(rc, "onyx_transport", cfg.onyx_transport)
    setattr(rc, "onyx_armed", False)           # sim-safe
    # deck-integrated VSpin for the nuclei spin (unless nuclei are pre-concentrated)
    setattr(rc, "centrifuge_enabled", cfg.centrifuge_enabled and not cfg.nuclei_preconcentrated)
    setattr(rc, "vspin_host", cfg.vspin_host)
    return rc
