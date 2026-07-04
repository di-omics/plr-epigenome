"""
Pure normalization math: measured concentrations -> per-well transfer plan.

No hardware, no I/O, so it is unit-testable on its own and is the part most worth
getting exactly right. For each well we compute how much sample and how much
water to combine to hit the target concentration at the target final volume, and
we classify wells that fall outside what the liquid handler can achieve.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List

from .config import NormConfig


@dataclass
class WellNorm:
    well: str
    conc_ng_per_ul: float          # measured source concentration
    sample_ul: float               # volume of source to transfer
    water_ul: float                # volume of water to add
    final_ng_per_ul: float         # achieved concentration in the dest well
    status: str                    # "ok" | "capped_low" | "needs_predilution" | "empty"


def _round(x: float, nd: int = 2) -> float:
    return round(x + 1e-9, nd)


def plan_well(well: str, conc: float, cfg: NormConfig) -> WellNorm:
    target = cfg.target_ng_per_ul
    vfinal = cfg.final_volume_ul
    usable = cfg.usable_source_ul
    vmin, vmax = cfg.min_transfer_ul, cfg.max_transfer_ul
    target_mass = target * vfinal          # ng we want in the dest well

    if conc <= 0:
        return WellNorm(well, _round(conc), 0.0, _round(vfinal), 0.0, "empty")

    v_needed = target_mass / conc          # ideal sample volume

    # Too concentrated: ideal transfer is below the smallest reliable volume, so
    # a single transfer would overshoot the target. Flag for pre-dilution.
    if v_needed < vmin:
        v = vmin
        water = max(vfinal - v, 0.0)
        final = conc * v / vfinal
        return WellNorm(well, _round(conc), _round(v), _round(water),
                        _round(final), "needs_predilution")

    # Too dilute: even all usable sample can't reach target in vfinal. Transfer
    # the max available, no water beyond filling, and flag under-target.
    cap = min(usable, vmax)
    if v_needed > cap:
        v = cap
        water = max(vfinal - v, 0.0)
        final = conc * v / vfinal
        return WellNorm(well, _round(conc), _round(v), _round(water),
                        _round(final), "capped_low")

    # In range: hit target exactly.
    v = v_needed
    water = max(vfinal - v, 0.0)
    return WellNorm(well, _round(conc), _round(v), _round(water), _round(target), "ok")


def build_plan(concs: dict, cfg: NormConfig) -> List[WellNorm]:
    """concs: {well_address: ng/uL}. Returns a WellNorm per well."""
    return [plan_well(well, c, cfg) for well, c in concs.items()]


def summarize(plan: List[WellNorm]) -> dict:
    counts = {"ok": 0, "capped_low": 0, "needs_predilution": 0, "empty": 0}
    for w in plan:
        counts[w.status] = counts.get(w.status, 0) + 1
    total_sample = sum(w.sample_ul for w in plan)
    total_water = sum(w.water_ul for w in plan)
    return {
        "counts": counts,
        "wells": len(plan),
        "total_sample_ul": _round(total_sample, 1),
        "total_water_ul": _round(total_water, 1),
        "detail": [asdict(w) for w in plan],
    }
