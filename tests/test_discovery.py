"""Tests for the minimal-effective-reaction discovery loop (plant-and-recover)."""

import math
import random
import statistics as st

from tipseq_plr.discovery.surface import ResponseSurface, to_real, KNOBS
from tipseq_plr.discovery.loop import DiscoveryConfig, DiscoveryLoop


def _cfg(**kw):
    # fast, deterministic config for tests
    return DiscoveryConfig(candidate_n=250, true_grid=16, **kw)


def _agg(strategy, n=12):
    feas, gaps, max_runs = 0, [], 0
    for seed in range(n):
        d = DiscoveryLoop(_cfg(seed=seed, strategy=strategy)).run()
        max_runs = max(max_runs, d["runs"])
        if d["found"] and d["feasible"]:
            feas += 1
            gaps.append(d["cost_gap"])
    return feas, gaps, max_runs


# -- surface / plant ---------------------------------------------------------
def test_true_minimum_is_on_the_feasible_frontier():
    s = ResponseSurface(seed=0)
    x, c = s.true_minimum(grid=18)
    assert s.feasible(x)
    cheaper = tuple(max(v - 0.15, 0.0) for v in x)   # spend less on every knob
    assert s.cost(cheaper) < c
    assert not s.feasible(cheaper)                    # and it no longer decides


def test_min_feasible_yield_hits_target():
    s = ResponseSurface(seed=0)
    y = s.min_feasible_yield()
    z = (y - s.threshold) / s.noise_sd
    prob = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    assert abs(prob - s.target) < 0.02


def test_evaluate_fault_rate_and_signal():
    s = ResponseSurface(seed=0, fault_rate=0.2)
    rng = random.Random(1)
    n, faults = 800, 0
    for _ in range(n):
        faults += s.evaluate((0.9, 0.9, 0.9), rng).fault
    assert 0.12 < faults / n < 0.28                   # roughly the configured rate
    hi = sum(s.evaluate((0.9, 0.9, 0.9), rng).decision for _ in range(n))
    lo = sum(s.evaluate((0.25, 0.25, 0.9), rng).decision for _ in range(n))
    assert hi > lo                                    # a richer recipe reads decisionable more often


def test_to_real_maps_knob_ranges():
    r0, r1 = to_real((0, 0, 0)), to_real((1, 1, 1))
    assert r0["pcr_cycles"] == 3 and r1["pcr_cycles"] == 15
    assert r1["input_ng"] > r0["input_ng"]
    assert abs(r0["reagent_frac"] - 0.25) < 1e-6 and abs(r1["reagent_frac"] - 1.0) < 1e-6
    assert abs(sum(k.cost_weight for k in KNOBS) - 1.0) < 1e-9


# -- recovery ----------------------------------------------------------------
def test_recovers_plant_in_far_fewer_runs_than_exhaustive():
    feas, gaps, max_runs = _agg("bo_honest")
    assert feas >= 9                                  # recovers a feasible minimal recipe most seeds
    assert st.median(gaps) < 0.30                     # and lands near the true minimum
    assert max_runs <= DiscoveryConfig().budget + 2
    # far cheaper than an exhaustive grid over the same knobs
    assert DiscoveryConfig().budget * 50 < 26 ** 3


def test_cv_cleaning_beats_naive():
    hf, hg, _ = _agg("bo_honest")
    nf, ng, _ = _agg("bo_naive")
    assert hf >= nf + 2                               # excluding CV faults recovers feasibly more often
    assert st.median(hg) <= st.median(ng)             # and at least as close to the true minimum


def test_determinism():
    a = DiscoveryLoop(_cfg(seed=5)).run()
    b = DiscoveryLoop(_cfg(seed=5)).run()
    assert a == b
