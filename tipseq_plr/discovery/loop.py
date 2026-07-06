"""
Closed-loop discovery orchestrator, plus scoring against the planted answer.

One iteration is the closed loop from the diagram: the agent proposes a recipe,
the recipe is "run" (here, the synthetic surface stands in for compile-and-run on
the STAR plus the Tecan read), the readout updates the surrogate, and the agent
proposes again, all under a run budget. At the end we recover the agent's
recommended minimal reaction and score it against the known true minimum.

Three strategies isolate the two ideas:

    bo_honest   smart acquisition, CV faults excluded (re-run instead)
    bo_naive    smart acquisition, CV faults kept  (a botched well reads as a bad recipe)
    random      random proposals,  CV faults excluded

bo_honest vs random shows the value of the agent. bo_honest vs bo_naive shows the
value of CV-cleaning the readout: without it, mechanical faults masquerade as
chemistry failures and the search drifts to a costlier recipe.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .surface import ResponseSurface, DIM, to_real, Vec
from .agent import CostAwareBO


@dataclass
class DiscoveryConfig:
    budget: int = 60                # total physical runs allowed
    n_seed: int = 10                # space-filling runs before the agent takes over
    fault_rate: float = 0.20
    surface_target: float = 0.90    # P(decisionable) needed for a recipe to be feasible
    yield_safety: float = 0.01      # margin the agent adds above the true feasibility yield
    bandwidth: float = 0.22
    beta: float = 0.5
    candidate_n: int = 400
    recommend_min_neff: float = 0.7
    true_grid: int = 26             # brute-force grid for the answer key (coarser = faster)
    seed: int = 0
    strategy: str = "bo_honest"     # bo_honest | bo_naive | random


class DiscoveryLoop:
    def __init__(self, cfg: DiscoveryConfig):
        self.cfg = cfg

    @property
    def _use_acquisition(self) -> bool:
        return self.cfg.strategy in ("bo_honest", "bo_naive")

    @property
    def _exclude_faults(self) -> bool:
        return self.cfg.strategy != "bo_naive"

    def _eval(self, s: ResponseSurface, agent: CostAwareBO, x: Vec, rng: random.Random) -> int:
        obs = s.evaluate(x, rng)
        if not obs.fault:
            agent.observe(x, obs.yield_obs)
            return 1
        if not self._exclude_faults:                 # naive: keep the faulted read (yield ~0)
            agent.observe(x, obs.yield_obs)
            return 1
        obs2 = s.evaluate(x, rng)                     # honest: flagged, so re-run once
        if not obs2.fault:
            agent.observe(x, obs2.yield_obs)
        return 2

    def run(self) -> Dict:
        cfg = self.cfg
        s = ResponseSurface(seed=cfg.seed, target=cfg.surface_target, fault_rate=cfg.fault_rate)
        rng = random.Random(cfg.seed + 1)
        agent = CostAwareBO(DIM, s.cost, yield_target=s.min_feasible_yield() + cfg.yield_safety,
                            bandwidth=cfg.bandwidth, beta=cfg.beta,
                            candidate_n=cfg.candidate_n, seed=cfg.seed + 2)
        prop_rng = random.Random(cfg.seed + 4)
        seed_rng = random.Random(cfg.seed + 3)

        runs = 0
        for _ in range(cfg.n_seed):
            if runs >= cfg.budget:
                break
            x = tuple(seed_rng.random() for _ in range(DIM))
            runs += self._eval(s, agent, x, rng)
        while runs < cfg.budget:
            x = agent.propose() if self._use_acquisition else prop_rng.choice(agent.candidates)
            runs += self._eval(s, agent, x, rng)

        rec = agent.recommend(min_n_eff=cfg.recommend_min_neff)
        return self._score(s, rec, runs)

    def _score(self, s: ResponseSurface, rec: Optional[Vec], runs: int) -> Dict:
        true_x, true_cost = s.true_minimum(grid=self.cfg.true_grid)
        out = {"strategy": self.cfg.strategy, "runs": runs,
               "true_cost": round(true_cost, 4), "true_recipe": to_real(true_x)}
        if rec is None:
            out.update({"found": False, "feasible": False, "rec_cost": None,
                        "cost_gap": None, "distance": None, "rec_recipe": None})
            return out
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(rec, true_x)))
        out.update({
            "found": True,
            "feasible": s.feasible(rec),                     # does the pick actually clear the bar?
            "rec_cost": round(s.cost(rec), 4),
            "cost_gap": round(s.cost(rec) - true_cost, 4),   # overspend vs the true minimum
            "distance": round(dist, 3),
            "rec_recipe": to_real(rec),
        })
        return out


def compare(budget: int = 40, seed: int = 0, fault_rate: float = 0.20) -> Dict[str, Dict]:
    """Run all three strategies at the same budget/seed and return their scores."""
    results = {}
    for strat in ("bo_honest", "bo_naive", "random"):
        cfg = DiscoveryConfig(budget=budget, seed=seed, fault_rate=fault_rate, strategy=strat)
        results[strat] = DiscoveryLoop(cfg).run()
    return results
