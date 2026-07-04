"""
Automated CUT&Tag orchestrator.

Reuses TIP-seq's shared front half, then diverges to direct PCR:

  1 targeting     conA capture -> primary Ab -> secondary Ab -> pA-Tn5   (steps.binding)
  2 tagmentation  activate 37C -> EDTA stop -> SDS/proteinase K          (steps.tagmentation)
  3 purify        2.0x SPRI, elute clean gDNA for PCR (beads discarded)
  4 index PCR     + i5/i7 + NEBNext 2X; 72C gap-fill then N cycles (ODTC)
  5 cleanup       1.1x SPRI, elute in 10 mM Tris
  6 QC            Tecan dsDNA quant (shared steps.qc)

Because CUT&Tag keeps cells on conA beads the whole way (every separation is a
magnet step) and never needs a cell sort, it runs fully autonomously end to end,
like plate/bulk TIP-seq.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ... import config as C
from ...backends import ProfileStep
from ...deck import build_deck
from ...devices import build_devices
from ...reagents import ReagentRegistry
from ...steps import LiquidOps, binding, tagmentation, qc
from ...steps.thermal import incubate_tc
from .config import CutAndTagConfig

logger = logging.getLogger("tipseq.cutandtag")


@dataclass
class CutAndTag:
    cfg: CutAndTagConfig

    def __post_init__(self):
        self.rc = self.cfg.to_run_config()
        self.deckmap = build_deck(self.cfg.num_samples)
        self.registry = ReagentRegistry.build()
        self.devices = build_devices(self.rc, self.deckmap)
        self.ops = LiquidOps(self.devices, self.deckmap, self.registry, self.rc)

    async def purify_gdna(self):
        """2.0x SPRI purify of tagmented gDNA; clean eluate for PCR (no beads)."""
        logger.info("== SPRI purify gDNA (elute %.0f uL for PCR) ==", self.cfg.pcr_dna_ul)
        await self.ops.spri_cleanup(
            ratio=self.cfg.spri_ratio_purify,
            elution_ul=self.cfg.pcr_dna_ul,
            elution_reagent=C.WATER,
            keep_beads=False,
        )

    async def index_pcr(self):
        cfg, rc = self.cfg, self.rc
        logger.info("== indexing PCR (%d cycles) ==", cfg.pcr_cycles)
        await self.ops.add_reagent(C.PCR_MASTERMIX, cfg.pcr_mastermix_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.INDEX_I5, cfg.index_i5_ul, new_tips_each_column=True)
        await self.ops.add_reagent(C.INDEX_I7, cfg.index_i7_ul, mix=True, new_tips_each_column=True)

        p = rc.pcr
        steps = [
            ProfileStep(p.gapfill.celsius, p.gapfill.seconds, "gap-fill"),
            ProfileStep(p.initial_denature.celsius, p.initial_denature.seconds, "init-denat"),
        ]
        for _ in range(cfg.pcr_cycles):
            steps.append(ProfileStep(p.denature.celsius, p.denature.seconds, "denat"))
            steps.append(ProfileStep(p.anneal_extend.celsius, p.anneal_extend.seconds, "anneal-ext"))
        steps.append(ProfileStep(p.final_extend.celsius, p.final_extend.seconds, "final-ext"))
        await incubate_tc(self.ops, steps, lid_celsius=105.0,
                          block_max_volume=cfg.pcr_dna_ul + cfg.pcr_mastermix_ul + 4)

    async def cleanup(self):
        logger.info("== post-PCR cleanup (1.1x SPRI) ==")
        await self.ops.spri_cleanup(
            ratio=self.cfg.spri_ratio_cleanup,
            elution_ul=self.cfg.final_elution_ul,
            elution_reagent=C.WATER,
            keep_beads=False,
        )

    async def run(self) -> dict:
        cfg = self.cfg
        logger.info("### CUT&Tag start: %d samples, targets: %s",
                    cfg.num_samples, ", ".join(cfg.antibody_targets))
        await self.devices.setup()
        try:
            await binding.run(self.ops, barcoded=False)     # shared front half
            await tagmentation.activate(self.ops)
            await tagmentation.stop_and_digest(self.ops)
            await self.purify_gdna()
            await self.index_pcr()
            await self.cleanup()
            report = await qc.run(self.ops)
            report["method"] = "cut_and_tag"
            report["samples"] = cfg.num_samples
            logger.info("### CUT&Tag complete")
            return report
        finally:
            await self.devices.stop()
