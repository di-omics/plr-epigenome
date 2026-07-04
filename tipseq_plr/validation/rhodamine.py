"""
Rhodamine B liquid-handling validation: the success criteria that gate the
"liquid tested" claim.

Method: dispense known target volumes of a Rhodamine B stock into wells (bringing
each to a common final volume), read fluorescence on the plate reader, and back-
calculate the delivered volume from a Rhodamine standard curve. Rhodamine B is
used because its signal is bright, stable, and linear in amount over a wide range.

A protocol step is LIQUID_TESTED only if, on the real STAR with paired plate-
reader data, ALL of the following hold:

  1. Paired data:  every dispensed well has a matching reader value, and each
     target volume has at least `min_replicates` wells.
  2. In range:     every reading sits inside the plate reader's linear range
     (above blank, below the top standard / saturation ceiling). Readings out of
     range cannot be trusted, so the step is UNTESTED, not "tested but failed".
  3. Linearity:    the Rhodamine standard curve is linear, R^2 >= `min_r2`.
  4. Accuracy:     per target volume, |mean delivered - target| / target is within
     the tier tolerance.
  5. Precision:    per target volume, replicate CV is within the tier tolerance.

If any check fails, the verdict is UNTESTED with the reasons listed. There is no
partial credit: "liquid tested" means the bar was cleared with Rhodamine B and
paired reader data, full stop.

Pure functions, no hardware, no I/O beyond what the caller passes in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Dict, List, Optional, Tuple

from .status import ValidationTier


@dataclass(frozen=True)
class VolumeTier:
    """Tolerances get looser as volumes shrink (sub-uL handling is genuinely harder)."""

    min_ul: float          # tier applies to targets >= this volume
    accuracy_pct: float    # max |mean - target| / target * 100
    cv_pct: float          # max replicate CV %


# Default tiers. Tune to your instrument's validated spec before making claims.
DEFAULT_TIERS: Tuple[VolumeTier, ...] = (
    VolumeTier(min_ul=10.0, accuracy_pct=5.0, cv_pct=3.0),
    VolumeTier(min_ul=2.0,  accuracy_pct=10.0, cv_pct=5.0),
    VolumeTier(min_ul=0.0,  accuracy_pct=15.0, cv_pct=8.0),
)


@dataclass
class RhodamineCriteria:
    min_r2: float = 0.995
    min_replicates: int = 3
    saturation_rfu: float = 60000.0         # reader ceiling; readings above are saturated
    range_margin: float = 0.02              # allow 2% outside std min/max before "out of range"
    tiers: Tuple[VolumeTier, ...] = DEFAULT_TIERS

    def tier_for(self, volume_ul: float) -> VolumeTier:
        for t in self.tiers:                # tiers are ordered high->low min_ul
            if volume_ul >= t.min_ul:
                return t
        return self.tiers[-1]


@dataclass
class Standard:
    volume_ul: float       # trusted-method delivered volume (or known amount)
    rfu: float


@dataclass
class Reading:
    well: str
    target_ul: float       # what the protocol asked the STAR to dispense
    rfu: float


@dataclass
class GroupResult:
    target_ul: float
    n: int
    mean_delivered_ul: float
    cv_pct: float
    accuracy_pct: float
    all_in_range: bool
    passed: bool
    reasons: List[str] = field(default_factory=list)


def _linfit(xs: List[float], ys: List[float]) -> Tuple[float, float, float]:
    """Least-squares y = m*x + b, plus R^2."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return 0.0, my, 0.0
    m = sxy / sxx
    b = my - m * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (m * x + b)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return m, b, r2


def evaluate(
    standards: List[Standard],
    readings: List[Reading],
    criteria: Optional[RhodamineCriteria] = None,
) -> dict:
    """Return the full verdict: tier (UNTESTED / LIQUID_TESTED), standard-curve
    fit, per-target-volume group stats, and the reasons behind the verdict."""
    c = criteria or RhodamineCriteria()
    reasons: List[str] = []

    # -- standard curve ------------------------------------------------------
    xs = [s.volume_ul for s in standards]
    ys = [s.rfu for s in standards]
    m, b, r2 = _linfit(xs, ys)
    lo_rfu, hi_rfu = (min(ys), max(ys)) if ys else (0.0, 0.0)
    if r2 < c.min_r2:
        reasons.append(f"standard curve R2 {r2:.4f} < {c.min_r2}")
    if m <= 0:
        reasons.append("standard curve slope not positive (bad Rhodamine series)")

    # -- group readings by target volume ------------------------------------
    groups: Dict[float, List[Reading]] = {}
    for r in readings:
        groups.setdefault(round(r.target_ul, 4), []).append(r)

    results: List[GroupResult] = []
    for target, rs in sorted(groups.items()):
        tier = c.tier_for(target)
        greasons: List[str] = []

        in_range = all(
            (lo_rfu * (1 - c.range_margin)) <= r.rfu <= min(hi_rfu * (1 + c.range_margin),
                                                            c.saturation_rfu)
            for r in rs
        )
        if not in_range:
            greasons.append("reading(s) outside plate-reader linear range")

        # back-calculate delivered volume from the curve
        delivered = [((r.rfu - b) / m) if m > 0 else 0.0 for r in rs]
        mvol = mean(delivered) if delivered else 0.0
        sd = pstdev(delivered) if len(delivered) > 1 else 0.0
        cv = (sd / mvol * 100.0) if mvol > 0 else float("inf")
        acc = (abs(mvol - target) / target * 100.0) if target > 0 else float("inf")

        if len(rs) < c.min_replicates:
            greasons.append(f"only {len(rs)} replicate(s) (< {c.min_replicates})")
        if acc > tier.accuracy_pct:
            greasons.append(f"accuracy {acc:.1f}% > {tier.accuracy_pct}%")
        if cv > tier.cv_pct:
            greasons.append(f"CV {cv:.1f}% > {tier.cv_pct}%")

        passed = not greasons
        results.append(GroupResult(target, len(rs), round(mvol, 3), round(cv, 2),
                                   round(acc, 2), in_range, passed, greasons))

    all_groups_pass = bool(results) and all(g.passed for g in results)
    if not results:
        reasons.append("no readings provided")
    for g in results:
        reasons.extend(f"{g.target_ul} uL: {r}" for r in g.reasons)

    liquid_tested = (r2 >= c.min_r2) and (m > 0) and all_groups_pass
    tier = ValidationTier.LIQUID_TESTED if liquid_tested else ValidationTier.UNTESTED

    return {
        "tier": tier.value,
        "liquid_tested": liquid_tested,
        "standard_curve": {"slope": m, "intercept": b, "r2": round(r2, 5),
                           "rfu_range": [lo_rfu, hi_rfu]},
        "groups": [g.__dict__ for g in results],
        "reasons": reasons,
    }
