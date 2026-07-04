"""
Stage 2 - tagmentation + gDNA recovery.

    Tag buffer (Dig-300 + 10 mM MgCl2), 37C 1 h  -> transposes ME-T7 into DNA
    stop with EDTA, add SDS + proteinase K, 50C 30 min
    2.0x SPRI purify tagmented gDNA, KEEPING beads for downstream gap-fill/IVT
"""

from __future__ import annotations

import logging

from .. import config as C
from ..devices import _sleep
from .thermal import incubate_hs

logger = logging.getLogger("tipseq.tagment")


async def activate(ops):
    cfg = ops.cfg
    logger.info("== tagmentation ==")
    vol = cfg.volumes.tagmentation
    await ops.add_reagent(C.TAG_BUFFER, vol, mix=True, new_tips_each_column=True)
    await incubate_hs(ops, cfg.temps.tagmentation, cfg.timings.tagmentation,
                      rpm=cfg.shake.incubation_rpm)


async def stop_and_digest(ops):
    """Stop tagmentation and release chromatin with SDS / proteinase K."""
    cfg = ops.cfg
    logger.info("== stop + proteinase K ==")
    await ops.add_reagent(C.EDTA_0_5M, cfg.volumes.edta_stop, mix=True,
                          new_tips_each_column=True)
    await _sleep(cfg.timings.edta_stop_soak, cfg)
    await ops.add_reagent(C.SDS_10, cfg.volumes.sds, mix=True, new_tips_each_column=True)
    await ops.add_reagent(C.PROTEINASE_K, cfg.volumes.proteinase_k,
                          new_tips_each_column=True)
    await incubate_hs(ops, cfg.temps.proteinase_k, cfg.timings.proteinase_k, rpm=0)


async def purify_gdna(ops):
    """2.0x SPRI purify of tagmented gDNA, keeping beads for the IVT cascade."""
    cfg = ops.cfg
    logger.info("== SPRI purify gDNA (beads retained) ==")
    await ops.spri_cleanup(
        ratio=cfg.volumes.spri_ratio_default,
        elution_ul=cfg.volumes.gapfill_water,   # resuspend in 8 uL water
        elution_reagent=C.WATER,
        keep_beads=True,
    )


async def run(ops, purify: bool = True):
    """Full stage 2. For sciTIP-seq, call with purify=False so the FACS
    redistribution can happen before gDNA purification/IVT."""
    await activate(ops)
    await stop_and_digest(ops)
    if purify:
        await purify_gdna(ops)
    logger.info("Stage 2 (tagmentation) complete (purify=%s).", purify)
