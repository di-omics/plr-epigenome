"""
Stage 4 - cDNA synthesis from the T7 RNA.

    first-strand: anneal random hexamer (70C 3 min), MMLV RT (22C 10' / 42C 60' /
                  70C 10'), then RNase H (37C 20 min)
    second-strand: anneal sss primer (65C 2 min), Taq extend (72C 8 min)
    purify:       2.0x SPRI, elute cDNA in 7 uL (beads retained for fragmentation)
"""

from __future__ import annotations

import logging

from .. import config as C
from ..backends import ProfileStep
from .thermal import incubate_tc

logger = logging.getLogger("tipseq.cdna")


async def first_strand(ops):
    cfg = ops.cfg
    logger.info("== first-strand synthesis ==")
    # anneal random hexamer
    await ops.add_reagent(C.RANDOM_HEXAMER, cfg.volumes.random_hexamer, mix=True,
                          new_tips_each_column=True)
    await incubate_tc(ops, [ProfileStep(cfg.temps.rt_anneal, cfg.timings.rt_anneal,
                                        "hexamer-anneal")], block_max_volume=16.0)
    # assemble RT reaction
    for reagent, vol in (
        (C.RT_BUFFER_5X, cfg.volumes.rt_buffer_5x),
        (C.DNTP_10MM, cfg.volumes.dntp),
        (C.DTT_100MM, cfg.volumes.dtt),
        (C.MMLV_RT, cfg.volumes.mmlv_rt),
    ):
        await ops.add_reagent(reagent, vol, new_tips_each_column=True)
    await incubate_tc(ops, [
        ProfileStep(cfg.temps.rt_step1, cfg.timings.rt_10, "RT-22C"),
        ProfileStep(cfg.temps.rt_step2, cfg.timings.rt_60, "RT-42C"),
        ProfileStep(cfg.temps.rt_term, cfg.timings.rt_term, "RT-inactivate"),
    ], block_max_volume=25.0)
    # RNase H to degrade RNA in the RNA:cDNA hybrid
    await ops.add_reagent(C.RNASE_H, cfg.volumes.rnase_h, mix=True,
                          new_tips_each_column=True)
    await incubate_tc(ops, [ProfileStep(cfg.temps.rnase_h, cfg.timings.rnase_h,
                                        "RNaseH")], block_max_volume=25.0)


async def second_strand(ops):
    cfg = ops.cfg
    logger.info("== second-strand synthesis ==")
    await ops.add_reagent(C.SSS_PRIMER, cfg.volumes.sss_primer, mix=True,
                          new_tips_each_column=True)
    await incubate_tc(ops, [ProfileStep(cfg.temps.sss_anneal, cfg.timings.sss_anneal,
                                        "sss-anneal")], block_max_volume=25.0)
    await ops.add_reagent(C.TAQ_5X, cfg.volumes.taq_second_strand, mix=True,
                          new_tips_each_column=True)
    await incubate_tc(ops, [ProfileStep(cfg.temps.sss_extend, cfg.timings.sss_extend,
                                        "sss-extend")], block_max_volume=30.0)


async def run(ops):
    cfg = ops.cfg
    await first_strand(ops)
    await second_strand(ops)
    logger.info("== SPRI purify cDNA (elute 7 uL, beads retained) ==")
    await ops.spri_cleanup(
        ratio=cfg.volumes.spri_ratio_default,
        elution_ul=cfg.volumes.cdna_elution,
        elution_reagent=C.WATER,
        keep_beads=True,
    )
    logger.info("Stage 4 (cDNA) complete.")
