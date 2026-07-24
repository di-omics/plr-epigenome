"""
Stage 5, library construction: fragment, index, size-select.

    fragmentation: + TAPS buffer + ME-B-only Tn5, 55C 6 min; quench with 4 M GuHCl
    purify:        2.0x SPRI, elute in 16 uL, discard beads (fresh eluate now)
    PCR indexing:  + high-fidelity 2X mix + i5 + i7; 72C gap-fill, then N cycles
    cleanup:       0.85x left-side SPRI size selection (>200 bp)
"""

from __future__ import annotations

import logging

from .. import config as C
from ..backends import ProfileStep
from ..devices import _sleep
from .thermal import incubate_tc

logger = logging.getLogger("tipseq.library")


async def fragment(ops):
    cfg = ops.cfg
    logger.info("== cDNA fragmentation (Tn5 ME-B, 55C) ==")
    await ops.add_reagent(C.TAPS_BUFFER, cfg.volumes.taps_buffer, new_tips_each_column=True)
    await ops.add_reagent(C.TN5_MEB, cfg.volumes.tn5_meb, mix=True, new_tips_each_column=True)
    await incubate_tc(ops, [ProfileStep(cfg.temps.fragmentation, cfg.timings.fragmentation,
                                        "fragment")], block_max_volume=12.0)
    # quench Tn5 with guanidine-HCl
    await ops.add_reagent(C.GUHCL, 4.0, mix=True, new_tips_each_column=True)
    # purify; this time keep the eluate, discard beads
    await ops.spri_cleanup(
        ratio=cfg.volumes.spri_ratio_default,
        elution_ul=cfg.volumes.frag_elution,
        elution_reagent=C.WATER,
        keep_beads=False,
    )


async def pcr_index(ops):
    cfg = ops.cfg
    logger.info("== PCR indexing (%d cycles) ==", cfg.pcr_cycles)
    await ops.add_reagent(C.PCR_MASTERMIX, cfg.volumes.pcr_mastermix, new_tips_each_column=True)
    # i5 / i7 are per-well index primers drawn from the index plate columns
    await ops.add_reagent(C.INDEX_I5, cfg.volumes.index_i5, new_tips_each_column=True)
    await ops.add_reagent(C.INDEX_I7, cfg.volumes.index_i7, mix=True, new_tips_each_column=True)

    p = cfg.pcr
    steps = [
        ProfileStep(p.gapfill.celsius, p.gapfill.seconds, "gap-fill"),
        ProfileStep(p.initial_denature.celsius, p.initial_denature.seconds, "init-denat"),
    ]
    for _ in range(cfg.pcr_cycles):
        steps.append(ProfileStep(p.denature.celsius, p.denature.seconds, "denat"))
        steps.append(ProfileStep(p.anneal_extend.celsius, p.anneal_extend.seconds, "anneal-ext"))
    steps.append(ProfileStep(p.final_extend.celsius, p.final_extend.seconds, "final-ext"))
    await incubate_tc(ops, steps, lid_celsius=105.0, block_max_volume=cfg.volumes.pcr_total)


async def size_select(ops):
    cfg = ops.cfg
    logger.info("== post-PCR cleanup + size selection (0.85x, >200 bp) ==")
    await ops.spri_cleanup(
        ratio=cfg.volumes.spri_ratio_sizeselect,
        elution_ul=30.0,
        elution_reagent=C.WATER,
        keep_beads=False,
    )


async def run(ops):
    await fragment(ops)
    await pcr_index(ops)
    await size_select(ops)
    logger.info("Stage 5 (library) complete.")
