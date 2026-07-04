"""
End-to-end orchestrator for automated (sci)TIP-seq on a Hamilton STAR.

Stages, in order:
  0  preload      cells aliquoted into the working plate (off-deck prep)
  1  targeting    conA capture -> primary Ab -> secondary Ab -> pA-Tn5 (binding.py)
  2  tagmentation activate -> stop/proteinaseK -> (purify) (tagmentation.py)
    ---- sciTIP-seq only: FACS re-distribution handoff here ----
  3  linear amp   gap-fill -> IVT -> RNA purify (ivt.py)
  4  cDNA         first/second strand -> purify (cdna.py)
  5  library      fragment -> PCR index -> size-select (library.py)
  6  QC           Tecan dsDNA quant + pass/dilute/fail gate (qc.py)

The FACS step is a hard automation boundary: a STAR cannot sort cells. For
SCITIP_SEQ the run stops after index-1 tagmentation and either (a) raises
`FacsHandoffRequired` on hardware so an operator sorts index-1 pooled cells into
the index-2 plate and calls `resume_after_facs()`, or (b) in simulation, prints
the handoff and continues so the whole flow can be validated in one shot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ...config import Method, RunConfig
from ...deck import build_deck, pin_labware
from ...devices import build_devices
from ...reagents import ReagentRegistry
from ...steps import LiquidOps, binding, tagmentation, ivt, cdna, library, qc

logger = logging.getLogger("tipseq.protocol")


class FacsHandoffRequired(Exception):
    """Raised on hardware at the sci FACS boundary to pause the automated run."""


@dataclass
class TipSeqProtocol:
    cfg: RunConfig

    def __post_init__(self):
        self.deckmap = build_deck(self.cfg.num_samples)
        self.registry = ReagentRegistry.build()
        self.devices = build_devices(self.cfg, self.deckmap)
        self.ops = LiquidOps(self.devices, self.deckmap, self.registry, self.cfg)
        self._sci = self.cfg.method == Method.SCITIP_SEQ

    # -- pre-flight ----------------------------------------------------------
    def loadout(self) -> dict:
        """Estimate reagent volumes to prepare and echo the labware to confirm."""
        v = self.cfg.volumes
        wells = self.cfg.num_samples
        # Rough per-well accounting across the run for operator prep.
        from ... import config as C
        table = [
            (C.CONA_BEADS, v.cona_bead_slurry, 1),
            (C.ANTIBODY_BUFFER, v.antibody_reaction, 1),
            (C.DIG_WASH, v.secondary_reaction + v.wash_volume_plate * 2, 1),
            (C.DIG_300, v.patn5_reaction + v.wash_volume_plate * 3, 1),
            (C.TAG_BUFFER, v.tagmentation, 1),
            (C.EDTA_0_5M, v.edta_stop, 1),
            (C.SDS_10, v.sds, 1),
            (C.PROTEINASE_K, v.proteinase_k, 1),
            (C.SPRI_BEADS, 200, 4),          # ~4 SPRI cleanups
            (C.ETHANOL_80, 150 * 2, 4),
            (C.WATER, 40, 5),
            (C.TAQ_5X, v.taq_gapfill + v.taq_second_strand, 1),
            (C.T7_NTP, v.t7_ntp, 1), (C.T7_BUFFER, v.t7_buffer, 1),
            (C.T7_POLYMERASE, v.t7_polymerase, 1), (C.RNASE_INHIBITOR, v.rnase_inhibitor, 1),
            (C.RANDOM_HEXAMER, v.random_hexamer, 1), (C.RT_BUFFER_5X, v.rt_buffer_5x, 1),
            (C.DNTP_10MM, v.dntp, 1), (C.DTT_100MM, v.dtt, 1), (C.MMLV_RT, v.mmlv_rt, 1),
            (C.RNASE_H, v.rnase_h, 1), (C.SSS_PRIMER, v.sss_primer, 1),
            (C.TAPS_BUFFER, v.taps_buffer, 1), (C.TN5_MEB, v.tn5_meb, 1),
            (C.GUHCL, 4.0, 1), (C.PCR_MASTERMIX, v.pcr_mastermix, 1),
            (C.INDEX_I5, v.index_i5, 1), (C.INDEX_I7, v.index_i7, 1),
            (C.QUANT_DYE, 98.0, 1),
        ]
        for name, per_well, times in table:
            self.registry.plan_load(name, per_well * times, wells=wells)
        return {"reagents": self.registry.loadout(), "labware": pin_labware()}

    # -- run -----------------------------------------------------------------
    async def preload_cells(self):
        logger.info("== preload: %d samples into working plate ==", self.cfg.num_samples)
        logger.info("targets: %s", ", ".join(self.cfg.antibody_targets))
        # Off-deck: cells harvested/permeabilized and aliquoted per well before start.
        for c in range(self.ops.ncols):
            self.ops.well_volume_ul[c] = 0.0

    async def run(self) -> dict:
        cfg = self.cfg
        logger.info("### (sci)TIP-seq automation start: method=%s samples=%d simulate=%s",
                    cfg.method.value, cfg.num_samples, cfg.simulate)
        await self.devices.setup()
        try:
            await self.preload_cells()

            # Stage 1: targeting
            await binding.run(self.ops, barcoded=self._sci)

            # Stage 2: tagmentation (sci defers gDNA purify until after FACS)
            await tagmentation.run(self.ops, purify=not self._sci)

            if self._sci:
                await self._facs_handoff()
                # after sorting into the index-2 plate, purify gDNA then continue
                await tagmentation.purify_gdna(self.ops)

            # Stage 3-5: amplification, cDNA, library
            await ivt.run(self.ops)
            await cdna.run(self.ops)
            await library.run(self.ops)

            # Stage 6: QC
            report = await qc.run(self.ops)
            report["method"] = cfg.method.value
            report["samples"] = cfg.num_samples
            logger.info("### run complete")
            return report
        finally:
            await self.devices.stop()

    async def _facs_handoff(self):
        """The sciTIP-seq index-1/index-2 boundary.

        Three outcomes, in priority order:
          1. A BD FACSMelody is configured (`sorter_enabled`) -> drive the sort
             automatically via the reverse-engineered ProtocolMap. This is the
             closed-loop path (STAR pools -> Melody sorts into index-2 plate).
          2. Simulation, no sorter -> log the boundary and continue.
          3. Hardware, no sorter -> raise so an operator sorts manually and calls
             resume_after_facs().
        """
        msg = (
            "sciTIP-seq FACS boundary: index-1 tagmented cells are pooled and must "
            "be FACS-redistributed into the index-2 plate (25-100 cells/well)."
        )
        if self.devices.sorter is not None:
            logger.info("FACS boundary: driving BD FACSMelody sort-to-plate.")
            # STAR pools index-1 wells + stages the index-2 plate off-deck to the
            # sorter (arm/hotel handoff); here we trigger the templated sort.
            await self.devices.sorter.sort_to_plate(
                cells_per_well=self.cfg.sort_cells_per_well,
                wells=self.cfg.num_samples,
                template=self.cfg.sorter_template,
            )
            return
        if self.cfg.simulate:
            logger.warning("[sim] %s  -- no sorter configured; continuing as if resumed.", msg)
            return
        raise FacsHandoffRequired(
            msg + " No FACSMelody configured; sort manually and call resume_after_facs().")

    async def resume_after_facs(self) -> dict:
        """Entry point to resume a real sci run once cells are sorted into the
        index-2 plate. Mirrors the post-FACS half of `run`."""
        await self.devices.setup()
        try:
            await tagmentation.purify_gdna(self.ops)
            await ivt.run(self.ops)
            await cdna.run(self.ops)
            await library.run(self.ops)
            report = await qc.run(self.ops)
            report["method"] = self.cfg.method.value
            report["resumed"] = True
            return report
        finally:
            await self.devices.stop()
