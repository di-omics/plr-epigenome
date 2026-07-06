"""
Cost-aware Bayesian-optimization-lite agent (pure Python, no numpy).

The agent does not optimize yield for its own sake. It optimizes toward the
DECISION under a cost penalty: find the cheapest recipe whose yield clears the QC
bar with margin. That constrained objective is what makes a reaction "minimal
effective" rather than just "high yield".

Surrogate: kernel-smoothed regression of the observed yield (the continuous
Tecan read) over the runs it has been given. For a candidate x it predicts the
local mean yield and an effective sample size; uncertainty falls as nearby runs
accumulate. A poor person's Gaussian process, but a real mean-plus-uncertainty
model that runs anywhere.

Acquisition: among candidates whose optimistic yield (mean plus an uncertainty
bonus) clears the target, take the cheapest, with a small explore bonus so
cheap-but-unproven regions get probed. Before anything looks feasible, push
toward the most promising region instead.
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

Vec = Tuple[float, ...]


class CostAwareBO:
    def __init__(self, dim: int, cost_fn, *, yield_target: float,
                 bandwidth: float = 0.15, beta: float = 0.6, explore: float = 0.10,
                 yield_scale: float = 0.25, candidate_n: int = 400, seed: int = 0):
        self.dim = dim
        self.cost_fn = cost_fn
        self.yield_target = yield_target      # predicted yield a recipe must reach
        self.bw = bandwidth
        self.beta = beta
        self.explore = explore
        self.yield_scale = yield_scale        # yield units per unit of uncertainty
        self.rng = random.Random(seed)
        self.candidates: List[Vec] = [
            tuple(self.rng.random() for _ in range(dim)) for _ in range(candidate_n)
        ]
        self.obs: List[Tuple[Vec, float]] = []   # (x, observed yield); faults excluded upstream

    def observe(self, x: Vec, yield_obs: float):
        self.obs.append((x, yield_obs))

    def _predict(self, x: Vec) -> Tuple[float, float]:
        """Return (predicted yield, effective sample size) at x."""
        if not self.obs:
            return 0.0, 0.0
        num = den = 0.0
        inv = 1.0 / (2.0 * self.bw * self.bw)
        for xi, y in self.obs:
            dist2 = sum((a - b) ** 2 for a, b in zip(x, xi))
            w = math.exp(-dist2 * inv)
            num += w * y
            den += w
        if den == 0.0:
            return 0.0, 0.0
        return num / den, den

    def _uncertainty(self, n_eff: float) -> float:
        return 1.0 / math.sqrt(n_eff + 1.0)

    def propose(self) -> Vec:
        best_x, best_score = None, float("inf")
        fallback_x, fallback_v = None, -1.0
        for x in self.candidates:
            mean, n_eff = self._predict(x)
            unc = self._uncertainty(n_eff)
            ucb = mean + self.beta * self.yield_scale * unc
            if ucb > fallback_v:
                fallback_v, fallback_x = ucb, x
            if ucb >= self.yield_target:                 # optimistically feasible
                score = self.cost_fn(x) - self.explore * unc
                if score < best_score:
                    best_score, best_x = score, x
        return best_x if best_x is not None else fallback_x

    def recommend(self, min_n_eff: float = 1.2) -> Optional[Vec]:
        """Cheapest recipe on the surrogate that clears the target with local
        evidence behind it. This is the point you would hand to the validation
        ladder for a confirming liquid test."""
        best_x, best_c = None, float("inf")
        for x in self.candidates:
            mean, n_eff = self._predict(x)
            if n_eff >= min_n_eff and mean >= self.yield_target:
                c = self.cost_fn(x)
                if c < best_c:
                    best_c, best_x = c, x
        return best_x
