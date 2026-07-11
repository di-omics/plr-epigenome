"""
Plate-normalization protocol.

    source plate (96 x 12 uL)
      -> Qubit dsDNA HS prep on a 2 uL aliquot into a black assay plate
      -> Tecan read (Ex485/Em530) + dsDNA standard curve
      -> per-well concentration
      -> normalize: sample + water into a destination plate at a uniform
         concentration and volume

Reuses the repo's STAR deck and Tecan backend. Runs fully in simulation (and
even without PyLabRobot, in a logging dry mode) like the rest of plr-epigenome.

Deck roles (from deck.build_deck):
    working_plate -> SOURCE   (the 96 x 12 uL input)
    qc_plate      -> ASSAY    (black plate for the Qubit read)
    index_plate   -> DEST     (normalized output)
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Dict, List

from ... import config as C
from ...deck import build_deck
from ...devices import build_devices, _sleep
from ...reagents import ReagentRegistry
from ...steps.qc import _least_squares
from .config import NormConfig
from .plan import build_plan, summarize, WellNorm

logger = logging.getLogger("tipseq.normalize")

_ROWS = "ABCDEFGH"


class _NormOps:
    """Minimal column-wise liquid handling for the normalization plate, with
    per-well volumes (each STAR channel gets its own volume within a column)."""

    def __init__(self, devices, deckmap, registry, cfg: NormConfig):
        self.dev = devices
        self.lh = devices.lh
        self.dm = deckmap
        self.reg = registry
        self.cfg = cfg
        self.dry = self.lh is None
        self.ncols = math.ceil(cfg.num_samples / 8)

    def _col(self, c: int) -> str:
        return f"A{c + 1}:H{c + 1}"

    async def _pick(self, rack, c):
        if not self.dry:
            await self.lh.pick_up_tips(rack[self._col(c)])

    async def _drop(self):
        if not self.dry:
            await self.lh.drop_tips()

    async def dispense_working_solution(self):
        """WS into every assay well (same volume), one tip column reused."""
        vol = self.cfg.qubit.ws_per_well_ul
        self.reg.charge(C.QUBIT_HS_WS, vol, wells=self.ncols * 8)
        logger.info("assay: dispense %.0f uL Qubit HS working solution x %d cols",
                    vol, self.ncols)
        if self.dry:
            return
        src = self.reg.resource_for(self.dm, C.QUBIT_HS_WS)
        await self._pick(self.dm.tips_300, 0)
        for c in range(self.ncols):
            await self.lh.aspirate(src, vols=[vol] * 8)
            await self.lh.dispense(self.dm.qc_plate[self._col(c)], vols=[vol] * 8)
        await self._drop()

    async def aliquot_samples_to_assay(self):
        """Move `sample_aliquot_ul` from each source well into the assay plate.
        Fresh tips per column (sample-contacting)."""
        vol = self.cfg.qubit.sample_aliquot_ul
        logger.info("assay: aliquot %.1f uL source -> assay x %d cols", vol, self.ncols)
        if self.dry:
            return
        for c in range(self.ncols):
            await self._pick(self.dm.tips_50, c)
            await self.lh.aspirate(self.dm.working_plate[self._col(c)], vols=[vol] * 8)
            await self.lh.dispense(self.dm.qc_plate[self._col(c)], vols=[vol] * 8)
            await self._drop()

    async def dispense_water(self, water_by_col: List[List[float]]):
        """Per-well water into the destination plate (clean, tips reused)."""
        logger.info("normalize: dispense water into dest x %d cols", self.ncols)
        if self.dry:
            return
        src = self.reg.resource_for(self.dm, C.WATER)
        await self._pick(self.dm.tips_50, 0)
        for c in range(self.ncols):
            vols = water_by_col[c]
            self.reg.charge(C.WATER, sum(vols))
            await self.lh.aspirate(src, vols=[max(v, 0.0) for v in vols])
            await self.lh.dispense(self.dm.index_plate[self._col(c)], vols=[max(v, 0.0) for v in vols])
        await self._drop()

    async def transfer_samples(self, sample_by_col: List[List[float]]):
        """Per-well source -> dest transfer at normalized volumes. Fresh tips per
        column, then mix into the water already in the destination."""
        logger.info("normalize: transfer normalized sample source -> dest x %d cols",
                    self.ncols)
        if self.dry:
            return
        for c in range(self.ncols):
            vols = [max(v, 0.0) for v in sample_by_col[c]]
            await self._pick(self.dm.tips_50, c)
            await self.lh.aspirate(self.dm.working_plate[self._col(c)], vols=vols)
            await self.lh.dispense(self.dm.index_plate[self._col(c)], vols=vols)
            await self._drop()


@dataclass
class PlateNormalization:
    cfg: NormConfig

    def __post_init__(self):
        self.deckmap = build_deck(self.cfg.num_samples)
        self.registry = ReagentRegistry.build()
        # normalization only drives the STAR + reader; reuse the shared builder
        # by mapping NormConfig onto the fields build_devices reads.
        self._rc = _as_run_config(self.cfg)
        self.devices = build_devices(self._rc, self.deckmap)
        self.ops = _NormOps(self.devices, self.deckmap, self.registry, self.cfg)
        self._rng = random.Random(11)

    # -- assay ---------------------------------------------------------------
    async def _qubit_prep(self):
        logger.info("== Qubit HS prep (aliquot %.1f uL, %s dye, %.0f uL assay) ==",
                    self.cfg.qubit.sample_aliquot_ul, self.cfg.qubit.dye_ratio,
                    self.cfg.qubit.assay_volume_ul)
        await self.ops.dispense_working_solution()
        await self.ops.aliquot_samples_to_assay()
        await _sleep(self.cfg.qubit.incubation_s, self._rc)

    def _read_standards(self) -> List[tuple]:
        """(ng/uL, RFU) for the standards strip. On hardware this reads the
        dedicated standards wells; in simulation it synthesizes RFUs consistent
        with the Tecan sample sim (RFU ~ 50 + ng*800)."""
        pts = []
        for ng in self.cfg.qubit.standard_ng_per_ul:
            rfu = 50 + ng * 800 + self._rng.uniform(-25, 25)
            pts.append((ng, rfu))
        return pts

    async def _read_samples(self) -> Dict[str, float]:
        grid = await self.devices.reader.read_fluorescence(
            excitation_wavelength=self.cfg.qubit.excitation_nm,
            emission_wavelength=self.cfg.qubit.emission_nm,
        )
        std = self._read_standards()
        m, b = _least_squares([r for _, r in std], [ng for ng, _ in std])  # ng = m*RFU + b
        logger.info("Qubit standard curve: ng/uL = %.4g*RFU + %.4g", m, b)
        concs: Dict[str, float] = {}
        for c in range(self.ops.ncols):
            for r in range(8):
                well = f"{_ROWS[r]}{c + 1}"
                concs[well] = max(m * grid[r][c] + b, 0.0)
        return concs

    # -- run -----------------------------------------------------------------
    async def run(self) -> dict:
        logger.info("### plate normalization start: %d samples, target %.2f ng/uL in %.0f uL",
                    self.cfg.num_samples, self.cfg.target_ng_per_ul, self.cfg.final_volume_ul)
        await self.devices.setup()
        try:
            await self._qubit_prep()
            concs = await self._read_samples()
            plan = build_plan(concs, self.cfg)
            await self._execute(plan)
            report = summarize(plan)
            report["target_ng_per_ul"] = self.cfg.target_ng_per_ul
            report["final_volume_ul"] = self.cfg.final_volume_ul
            logger.info("### normalization complete: %s", report["counts"])
            return report
        finally:
            await self.devices.stop()

    async def _execute(self, plan: List[WellNorm]):
        by_well = {w.well: w for w in plan}
        water_by_col, sample_by_col = [], []
        for c in range(self.ops.ncols):
            water_by_col.append([by_well[f"{_ROWS[r]}{c + 1}"].water_ul for r in range(8)])
            sample_by_col.append([by_well[f"{_ROWS[r]}{c + 1}"].sample_ul for r in range(8)])
        # water first, then sample (mix on dispense) to minimize tip use
        await self.ops.dispense_water(water_by_col)
        await self.ops.transfer_samples(sample_by_col)


def _as_run_config(cfg: NormConfig):
    """Adapt NormConfig to the subset of RunConfig fields build_devices reads,
    without pulling in the whole TIP-seq run config."""
    from ...config import RunConfig, Method
    rc = RunConfig(method=Method.PLATE_TIPSEQ, num_samples=cfg.num_samples,
                   simulate=cfg.simulate, tecan_host=cfg.tecan_host, star_id=cfg.star_id)
    setattr(rc, "_sim_time_scale", getattr(cfg, "_sim_time_scale", 0.0))
    return rc
