"""
Synthetic response surface for the minimal-effective-reaction search.

This is the plant in plant-and-recover. It stands in for a real closed loop,
which would require an independently reviewed operator method, a run, and a
Tecan QC read. Here it is modeled with a known synthetic surface so we can
score how well the agent recovers a KNOWN answer, and how few runs it needs,
with no hardware.

The recipe has three titratable, cost-bearing knobs (each normalized to [0,1]):

    pcr_cycles    more cycles amplify yield but cost time
    input_ng      more input raises yield but spends precious sample
    reagent_frac  miniaturization: below a floor, efficiency falls off a cliff

Library yield rises with all three and saturates. A well is "decisionable" when
its yield clears a QC threshold. Cost rises with every knob, so the minimal
effective reaction is the cheapest knob setting whose yield still clears the bar.
A run can also suffer a mechanical fault (bead loss): yield tanks, but the fault
is flagged (the CV layer), so an honest search excludes it instead of reading it
as a chemistry failure.

Pure Python. No numpy, no hardware.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Tuple

Vec = Tuple[float, ...]


@dataclass(frozen=True)
class Knob:
    name: str
    lo: float
    hi: float
    is_int: bool
    log: bool
    cost_weight: float


# order fixes the vector layout; cost_weights sum to 1.0
KNOBS: List[Knob] = [
    Knob("pcr_cycles", 3, 15, True, False, 0.40),
    Knob("input_ng", 1, 250, False, True, 0.35),
    Knob("reagent_frac", 0.25, 1.0, False, False, 0.25),
]
DIM = len(KNOBS)


def to_real(x: Vec) -> dict:
    """Map a normalized [0,1]^d vector to real protocol parameters."""
    out = {}
    for xi, k in zip(x, KNOBS):
        if k.log:
            v = math.exp(math.log(k.lo) + xi * (math.log(k.hi) - math.log(k.lo)))
        else:
            v = k.lo + xi * (k.hi - k.lo)
        out[k.name] = int(round(v)) if k.is_int else round(v, 3)
    return out


def cost(x: Vec) -> float:
    """Normalized run cost: each knob adds cost proportional to how high it is."""
    return sum(xi * k.cost_weight for xi, k in zip(x, KNOBS))


def _smoothstep(v: float, a: float, b: float) -> float:
    if v <= a:
        return 0.0
    if v >= b:
        return 1.0
    t = (v - a) / (b - a)
    return t * t * (3.0 - 2.0 * t)


@dataclass
class Observation:
    x: Vec
    yield_obs: float
    decision: bool          # did this run read as decisionable (crossed QC)?
    cost: float
    fault: bool             # mechanical fault seen by the CV layer (bead loss etc.)


class ResponseSurface:
    def __init__(self, seed: int = 0, threshold: float = 0.55, target: float = 0.90,
                 fault_rate: float = 0.18, noise_sd: float = 0.03):
        self.seed = seed
        self.threshold = threshold      # yield a single run needs to read decisionable
        self.target = target            # required P(decisionable) for a recipe to be feasible
        self.fault_rate = fault_rate
        self.noise_sd = noise_sd

    # -- the planted truth ---------------------------------------------------
    def yield_true(self, x: Vec) -> float:
        cy, inp, rg = x
        amp = 1.0 - math.exp(-3.0 * cy)          # cycles: diminishing returns
        mat = 1.0 - math.exp(-2.5 * inp)         # input: diminishing returns
        eff = _smoothstep(rg, 0.30, 0.55)        # reagent: miniaturization cliff
        return amp * mat * eff

    def decision_prob(self, x: Vec) -> float:
        # P(a single noisy run reads at or above the QC threshold)
        z = (self.yield_true(x) - self.threshold) / self.noise_sd
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    def feasible(self, x: Vec) -> bool:
        return self.decision_prob(x) >= self.target

    def min_feasible_yield(self) -> float:
        """The true yield a recipe must reach for P(decisionable) >= target."""
        lo, hi = self.threshold, 1.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            z = (mid - self.threshold) / self.noise_sd
            if 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))) < self.target:
                lo = mid
            else:
                hi = mid
        return hi

    def cost(self, x: Vec) -> float:
        return cost(x)

    # -- a noisy run, with the occasional flagged fault ----------------------
    def evaluate(self, x: Vec, rng: random.Random) -> Observation:
        if rng.random() < self.fault_rate:
            # bead loss / no pellet: yield collapses, but the CV layer flags it
            return Observation(x, yield_obs=max(0.0, rng.gauss(0.03, 0.02)),
                               decision=False, cost=cost(x), fault=True)
        y = self.yield_true(x) + rng.gauss(0.0, self.noise_sd)
        return Observation(x, yield_obs=y, decision=(y >= self.threshold),
                           cost=cost(x), fault=False)

    # -- the answer key ------------------------------------------------------
    def true_minimum(self, grid: int = 26) -> Tuple[Vec, float]:
        """Cheapest feasible recipe on the true surface (brute force)."""
        best_x, best_c = None, float("inf")
        for i in range(grid):
            for j in range(grid):
                for k in range(grid):
                    x = (i / (grid - 1), j / (grid - 1), k / (grid - 1))
                    if self.feasible(x):
                        c = cost(x)
                        if c < best_c:
                            best_c, best_x = c, x
        return best_x, best_c
