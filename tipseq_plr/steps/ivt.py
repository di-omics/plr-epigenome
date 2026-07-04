"""
Stage 3 - linear amplification: gap-fill then in-vitro transcription.

    gap-fill:  + Taq 5X master mix, 72C 3 min (fills the transposon gap)
    IVT:       + NTPs, T7 buffer, T7 polymerase, RNase inhibitor; 37C 16-19 h
    purify:    2.0x SPRI, elute RNA in 9 uL nuclease-free water (beads retained)

IVT is the rate-limiting wall-clock step (~17 h). On hardware this is a long ODTC
block hold; in simulation it is compressed by the sim time scale.
"""

from __future__ import annotations

import logging

from .. import config as C
from ..backends import ProfileStep
from ..devices import _sleep
from .thermal import incubate_tc

logger = logging.getLogger("tipseq.ivt")


async def run(ops):
    cfg = ops.cfg

    logger.info("== gap-fill (72C 3 min) ==")
    await ops.add_reagent(C.TAQ_5X, cfg.volumes.taq_gapfill, mix=True,
                          new_tips_each_column=True)
    await incubate_tc(
        ops,
        [ProfileStep(cfg.temps.gapfill, cfg.timings.gapfill, "gap-fill")],
        lid_celsius=105.0,
        block_max_volume=cfg.volumes.gapfill_water + cfg.volumes.taq_gapfill,
    )

    logger.info("== IVT (T7, 37C ~%.0f h) ==", cfg.ivt_hours)
    for reagent, vol in (
        (C.T7_NTP, cfg.volumes.t7_ntp),
        (C.T7_BUFFER, cfg.volumes.t7_buffer),
        (C.T7_POLYMERASE, cfg.volumes.t7_polymerase),
        (C.RNASE_INHIBITOR, cfg.volumes.rnase_inhibitor),
    ):
        await ops.add_reagent(reagent, vol, new_tips_each_column=True)
    # mix once assembled, then long block hold on the ODTC
    ivt_seconds = int(cfg.ivt_hours * 3600)
    await incubate_tc(
        ops,
        [ProfileStep(cfg.temps.ivt, ivt_seconds, "IVT")],
        lid_celsius=40.0,  # keep lid just above block to prevent condensation
        block_max_volume=16.0,
    )

    logger.info("== SPRI purify RNA (elute 9 uL, beads retained) ==")
    await ops.spri_cleanup(
        ratio=cfg.volumes.spri_ratio_default,
        elution_ul=cfg.volumes.rna_elution,
        elution_reagent=C.WATER,
        keep_beads=True,
    )
    logger.info("Stage 3 (linear amplification) complete.")
