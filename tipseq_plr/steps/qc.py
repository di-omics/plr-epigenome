"""
Stage 6 - library QC on the Tecan Infinite 200 Pro.

Fluorometric dsDNA quantification: transfer a small aliquot of each finished
library into a black QC plate containing intercalating dye, read Ex485/Em530,
fit the on-plate standard curve (column 1), convert every sample well to ng/uL,
and apply pass/dilute/fail gates. Returns a structured report; nothing is pooled
that hasn't passed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Dict, List

from .. import config as C
from ..devices import _sleep

logger = logging.getLogger("tipseq.qc")


@dataclass
class WellQC:
    well: str
    rfu: float
    ng_per_ul: float
    verdict: str  # "pass" | "dilute" | "fail"


def _least_squares(xs: List[float], ys: List[float]):
    """Fit y = m*x + b. Returns (m, b). Pure Python, no numpy dependency."""
    n = len(xs)
    sx = sum(xs); sy = sum(ys)
    sxx = sum(x * x for x in xs); sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, 0.0
    m = (n * sxy - sx * sy) / denom
    b = (sy - m * sx) / n
    return m, b


async def run(ops) -> Dict:
    cfg = ops.cfg
    qc = cfg.qc
    logger.info("== library QC (Tecan Pro 200 fluorescence) ==")

    # QC plate layout: dsDNA standard curve occupies column 12 (grid index 11),
    # pre-loaded by the operator; library aliquots go into columns matching the
    # processed working columns (working col c -> QC col c+1 -> grid index c).
    STD_COL = 11
    if not ops.dry:
        # dye working solution into all QC wells
        await ops.add_reagent(C.QUANT_DYE, 98.0, new_tips_each_column=True)
        # 2 uL of each library into the matching QC column
        for c in range(ops.ncols):
            await ops._pick(c)
            await ops._asp(ops._wells(c), 2.0)
            await ops._disp(ops.deckmap.qc_plate[ops._col(c)], 2.0)
            await ops._drop()

    await ops.to_reader()
    grid = await ops.dev.reader.read_fluorescence(
        excitation_wavelength=qc.excitation_nm,
        emission_wavelength=qc.emission_nm,
    )

    # standard curve from the standards column
    std_rfu = [grid[r][STD_COL] for r in range(8)]
    std_ng = list(qc.standard_curve_ng)
    m, b = _least_squares(std_rfu, std_ng)   # ng = m*RFU + b
    logger.info("standard curve: ng = %.4g*RFU + %.4g", m, b)

    rows = "ABCDEFGH"
    wells: List[WellQC] = []
    passed = diluted = failed = 0
    for c in range(ops.ncols):                # only processed sample columns
        for r in range(8):
            rfu = grid[r][c]
            conc = max(m * rfu + b, 0.0)
            if conc < qc.min_library_ng_per_ul:
                verdict = "fail"; failed += 1
            elif conc > qc.saturation_ng_per_ul:
                verdict = "dilute"; diluted += 1
            else:
                verdict = "pass"; passed += 1
            wells.append(WellQC(f"{rows[r]}{c + 1}", round(rfu, 1), round(conc, 3), verdict))

    report = {
        "standard_curve": {"slope": m, "intercept": b},
        "counts": {"pass": passed, "dilute": diluted, "fail": failed},
        "wells": [asdict(w) for w in wells],
    }
    logger.info("QC: %d pass, %d dilute, %d fail", passed, diluted, failed)
    return report
