"""
Stage 1 - targeting: bind cells, antibodies, and pA-Tn5.

Follows the paper's CUT&Tag front end (conA-bead format, which is what makes the
run fully deck-resident):

    conA beads -> cells  (10 min RT, rotation)
    primary antibody     (1:100, overnight 4C)
    secondary antibody   (1:100, 1 h RT)
    pA-Tn5 (T7 transposon)(1:100, 1 h RT) in Dig-300
    3x Dig-300 washes to remove unbound pA-Tn5

For sciTIP-seq, the pA-Tn5 carries a *barcoded* ME-T7 transposon per well
(index 1); that only changes which transposome reservoir each column draws from,
handled by `load_barcoded_patn5`.
"""

from __future__ import annotations

import logging

from .. import config as C
from ..devices import _sleep
from .thermal import incubate_hs

logger = logging.getLogger("tipseq.binding")


async def cona_capture(ops):
    """Bind conA beads to cells, then keep cells bead-immobilized for washes."""
    cfg = ops.cfg
    logger.info("== conA capture ==")
    # cells are already aliquoted into the working plate (see protocol preload)
    await ops.add_reagent(C.CONA_BEADS, cfg.volumes.cona_bead_slurry, mix=True,
                          new_tips_each_column=True)
    await incubate_hs(ops, cfg.temps.room_temp, cfg.timings.cona_bind,
                      rpm=cfg.shake.incubation_rpm)
    await ops.dev.magnet.engage(ops.lh, ops.plate, settle_s=120)
    await ops.remove_supernatant()
    await ops.dev.magnet.disengage(ops.lh, ops.plate)


async def primary_antibody(ops):
    cfg = ops.cfg
    logger.info("== primary antibody (overnight 4C) ==")
    await ops.add_reagent(C.ANTIBODY_BUFFER, cfg.volumes.antibody_reaction, mix=True,
                          new_tips_each_column=True)
    # antibody itself is spiked 1:100 into antibody buffer; in a per-target run
    # each column gets its own antibody from the index/enzyme carrier.
    await incubate_hs(ops, cfg.temps.primary_antibody, cfg.timings.primary_antibody,
                      rpm=cfg.shake.incubation_rpm)
    await ops.dev.magnet.engage(ops.lh, ops.plate, settle_s=120)
    await ops.remove_supernatant()
    await ops.dev.magnet.disengage(ops.lh, ops.plate)


async def secondary_antibody(ops):
    cfg = ops.cfg
    logger.info("== secondary antibody (1 h RT) ==")
    await ops.add_reagent(C.DIG_WASH, cfg.volumes.secondary_reaction, mix=True,
                          new_tips_each_column=True)
    await incubate_hs(ops, cfg.temps.room_temp, cfg.timings.secondary_antibody,
                      rpm=cfg.shake.incubation_rpm)
    # two Dig-wash washes
    await ops.dev.magnet.engage(ops.lh, ops.plate, settle_s=120)
    await ops.remove_supernatant()
    await ops.dev.magnet.disengage(ops.lh, ops.plate)
    await ops.wash_on_magnet(C.DIG_WASH, cfg.volumes.wash_volume_plate, times=2,
                             soak_s=cfg.timings.wash_soak)


async def load_barcoded_patn5(ops):
    """sci path: each column receives a uniquely barcoded ME-T7 pA-Tn5 (index 1).

    In this simplified reservoir model the 384 barcoded transposomes are laid out
    so column c draws from its own index-1 well. Physically these are preassembled
    in a source plate; here we just route the pipetting per column."""
    cfg = ops.cfg
    vol = cfg.volumes.patn5_reaction_sci
    logger.info("== load barcoded pA-Tn5 (index 1) ==")
    if ops.dry:
        for c in range(ops.ncols):
            logger.info("col %d <- barcoded pA-Tn5 %.1f uL (Dig-300)", c, vol)
            ops.well_volume_ul[c] += vol
        return
    for c in range(ops.ncols):
        # index source: index plate column c (r5 barcode), diluted into Dig-300
        src = ops.deckmap.index_plate[ops._col(c)]
        await ops._pick(c)
        await ops._asp(src, vol)
        await ops._disp(ops._wells(c), vol)
        ops.well_volume_ul[c] += vol
        await ops._drop()


async def patn5_binding(ops, barcoded: bool = False):
    cfg = ops.cfg
    logger.info("== pA-Tn5 binding (1 h RT) ==")
    if barcoded:
        await load_barcoded_patn5(ops)
    else:
        await ops.add_reagent(C.DIG_300, cfg.volumes.patn5_reaction, mix=True,
                              new_tips_each_column=True)
    await incubate_hs(ops, cfg.temps.binding, cfg.timings.patn5_bind,
                      rpm=cfg.shake.incubation_rpm)
    # 3x Dig-300 washes to remove unbound pA-Tn5
    await ops.dev.magnet.engage(ops.lh, ops.plate, settle_s=120)
    await ops.remove_supernatant()
    await ops.dev.magnet.disengage(ops.lh, ops.plate)
    await ops.wash_on_magnet(C.DIG_300, cfg.volumes.wash_volume_plate, times=3,
                             soak_s=cfg.timings.wash_soak)


async def run(ops, barcoded: bool = False):
    await cona_capture(ops)
    await primary_antibody(ops)
    await secondary_antibody(ops)
    await patn5_binding(ops, barcoded=barcoded)
    logger.info("Stage 1 (targeting) complete.")
