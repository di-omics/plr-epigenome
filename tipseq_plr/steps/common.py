"""
Reusable liquid-handling primitives shared by every biochemistry step.

`LiquidOps` is column-oriented: a 96-well working plate is 12 columns of 8, and
the STAR's 8 channels service one column per pass. All sample-facing volumes are
tracked in `well_volume_ul` so SPRI ratios and supernatant removals are computed
from the *actual* current volume rather than hard-coded.

Two execution modes, decided once at construction:
  * `self.dry` True  -> PyLabRobot isn't present; ops log their intent only.
  * `self.dry` False -> real `lh` calls (chatterbox in sim, STAR on hardware).
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional

from .. import config as C
from ..devices import _move_plate, _sleep
from . import vision as V

logger = logging.getLogger("tipseq.ops")


class LiquidOps:
    def __init__(self, devices, deckmap, registry, cfg, vision=None):
        self.dev = devices
        self.lh = devices.lh
        self.deckmap = deckmap
        self.reg = registry
        self.cfg = cfg
        self.vision = vision           # optional in-process CV checkpoints (None = off)
        self.dry = self.lh is None
        self.plate = deckmap.working_plate
        self.ncols = math.ceil(cfg.num_samples / 8)
        # per-column current liquid volume in the sample wells
        self.well_volume_ul: List[float] = [0.0] * self.ncols

    # -- addressing ----------------------------------------------------------
    def _col(self, c: int) -> str:
        return f"A{c + 1}:H{c + 1}"

    def _tips(self, c: int):
        rack = self.deckmap.tips_300
        return None if self.dry else rack[self._col(c)]

    def _wells(self, c: int):
        return None if self.dry else self.plate[self._col(c)]

    # -- atomic wrappers (guarded so a dry run never touches PLR) -------------
    async def _pick(self, c: int):
        if self.dry:
            return
        await self.lh.pick_up_tips(self._tips(c))

    async def _drop(self):
        if self.dry:
            return
        await self.lh.drop_tips()  # to trash

    async def _asp(self, resource, vol: float):
        if self.dry:
            return
        await self.lh.aspirate(resource, vols=[vol] * 8)

    async def _disp(self, resource, vol: float):
        if self.dry:
            return
        await self.lh.dispense(resource, vols=[vol] * 8)

    async def _mix(self, c: int, vol: float, cycles: int = 8):
        """Pipette up/down in place to resuspend beads / homogenize a reaction."""
        if self.dry:
            return
        wells = self._wells(c)
        for _ in range(cycles):
            await self.lh.aspirate(wells, vols=[vol] * 8)
            await self.lh.dispense(wells, vols=[vol] * 8)

    # -- high-level reagent handling ----------------------------------------
    async def add_reagent(
        self,
        reagent: str,
        volume_ul: float,
        *,
        mix: bool = False,
        new_tips_each_column: bool = False,
    ):
        """Dispense `volume_ul` of a reagent into every active sample column.

        Clean reagents reuse one tip column across all sample columns; set
        `new_tips_each_column` for anything that contacts sample (avoids
        carryover)."""
        self.reg.charge(reagent, volume_ul, wells=self.ncols * 8)
        src = None if self.dry else self.reg.resource_for(self.deckmap, reagent)
        logger.info("add %-20s %5.1f uL x %d cols", reagent, volume_ul, self.ncols)

        if not new_tips_each_column:
            await self._pick(0)
        for c in range(self.ncols):
            if new_tips_each_column:
                await self._pick(c)
            await self._asp(src, volume_ul)
            await self._disp(self._wells(c), volume_ul)
            self.well_volume_ul[c] += volume_ul
            if mix:
                await self._mix(c, min(self.well_volume_ul[c] * 0.6, 100))
            if new_tips_each_column:
                await self._drop()
        if not new_tips_each_column:
            await self._drop()

    async def remove_supernatant(self, volume_ul: Optional[float] = None, to_waste=True):
        """Aspirate supernatant off pelleted beads (plate must be on magnet).
        Fresh tips per column, discarded, to prevent cross-contamination."""
        logger.info("remove supernatant (%s)", "all" if volume_ul is None else f"{volume_ul} uL")
        for c in range(self.ncols):
            v = self.well_volume_ul[c] if volume_ul is None else volume_ul
            await self._pick(c)
            # aspirate slightly above the pellet; leave a hair to avoid bead loss
            await self._asp(self._wells(c), max(v - 2, 0))
            await self._drop()  # supernatant to trash
            self.well_volume_ul[c] = max(self.well_volume_ul[c] - v, 0.0)

    async def wash_on_magnet(self, reagent: str, volume_ul: float, times: int = 3, soak_s: int = 300):
        """Repeated buffer washes with the plate on the magnet (e.g. Dig-300)."""
        for i in range(times):
            logger.info("magnet wash %d/%d with %s", i + 1, times, reagent)
            await self.add_reagent(reagent, volume_ul, new_tips_each_column=True)
            await _sleep(soak_s, self.cfg)
            await self.remove_supernatant()

    # -- SPRI / bead cleanup (the workhorse) --------------------------------
    async def spri_cleanup(
        self,
        *,
        ratio: float,
        elution_ul: float,
        elution_reagent: str = C.WATER,
        keep_beads: bool = False,
        ethanol_washes: int = 2,
        etoh_ul: float = 150.0,
    ):
        """Standard SPRI purification.

        ratio        : bead:sample volume ratio (2.0x cleanup, 0.85x size-select)
        elution_ul   : final resuspension volume
        keep_beads   : if True, DNA is resuspended *with* beads left in (the paper
                       carries beads through gap-fill/IVT/cDNA); the eluate is not
                       separated onto the magnet.
        """
        cfg = self.cfg
        # 1) add beads proportional to current volume, mix, bind
        for c in range(self.ncols):
            bead_vol = self.well_volume_ul[c] * ratio
            src = None if self.dry else self.reg.resource_for(self.deckmap, C.SPRI_BEADS)
            self.reg.charge(C.SPRI_BEADS, bead_vol, wells=8)
            await self._pick(c)
            await self._asp(src, bead_vol)
            await self._disp(self._wells(c), bead_vol)
            self.well_volume_ul[c] += bead_vol
            await self._mix(c, min(self.well_volume_ul[c] * 0.5, 100))
            await self._drop()
        await _sleep(cfg.timings.bead_bind, cfg)

        # 2) engage magnet, pull supernatant. CV checkpoints here: the reader is
        # blind to bead loss, and this is where it happens.
        await self.dev.magnet.engage(self.lh, self.plate, settle_s=180)
        if self.vision:
            await self.vision.check(V.CHECK_BEAD_PELLET, step="spri_bind")
        await self.remove_supernatant()
        if self.vision:
            await self.vision.check(V.CHECK_SUPERNATANT, step="spri_bind")

        # 3) ethanol washes on the magnet
        for w in range(ethanol_washes):
            await self.add_reagent(C.ETHANOL_80, etoh_ul, new_tips_each_column=True)
            await _sleep(30, cfg)
            await self.remove_supernatant(volume_ul=etoh_ul)
        # dry residual ethanol, then confirm the beads are glossy, not over-dried
        await _sleep(cfg.timings.bead_dry, cfg)
        if self.vision:
            await self.vision.check(V.CHECK_NOT_OVERDRIED, step="spri_dry")

        # 4) elute
        await self.dev.magnet.disengage(self.lh, self.plate, to_site=self.deckmap.hhs_site)
        await self.add_reagent(elution_reagent, elution_ul, mix=True, new_tips_each_column=True)
        for c in range(self.ncols):
            self.well_volume_ul[c] = elution_ul

        if keep_beads:
            logger.info("SPRI done; beads retained in reaction (%.1f uL)", elution_ul)
            return
        # separate clean eluate from beads
        await self.dev.magnet.engage(self.lh, self.plate, settle_s=120)
        logger.info("SPRI done; eluate cleared of beads (%.1f uL)", elution_ul)
        await self.dev.magnet.disengage(self.lh, self.plate, to_site=self.deckmap.hhs_site)

    # -- plate hand-offs ----------------------------------------------------
    async def to_thermocycler(self):
        await _move_plate(self.lh, self.plate, self.deckmap.odtc_site, self.cfg.simulate)

    async def to_heatershaker(self):
        await _move_plate(self.lh, self.plate, self.deckmap.hhs_site, self.cfg.simulate)

    async def to_reader(self):
        await _move_plate(self.lh, self.plate, self.deckmap.reader_staging, self.cfg.simulate)
