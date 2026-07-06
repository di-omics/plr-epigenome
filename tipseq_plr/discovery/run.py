"""
Discovery loop: rediscover a planted minimal effective reaction, plant-and-recover.

    # find the cheapest recipe that still decides, then compare strategies
    python -m tipseq_plr.discovery.run --budget 60 -v
    python -m tipseq_plr.discovery.run --seed 3 --fault-rate 0.25 --report discovery.json

The plant is a synthetic response surface with a KNOWN cheapest feasible recipe.
The agent runs a cost-constrained closed loop (propose, run, read, update) under a
run budget and recovers a recipe blind. We then score it against the plant and
against two baselines. The honest arm excludes CV-flagged mechanical faults; the
naive arm keeps them, so a botched well reads as a bad recipe.
"""

from __future__ import annotations

import argparse
import json
import sys

from .loop import DiscoveryConfig, DiscoveryLoop, compare
from .surface import ResponseSurface, to_real


def _parse(argv=None):
    p = argparse.ArgumentParser(description="Agentic discovery of a minimal effective reaction")
    p.add_argument("--budget", type=int, default=60, help="total robot runs allowed")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--fault-rate", type=float, default=0.18, help="per-run mechanical fault probability")
    p.add_argument("--grid", type=int, default=26, help="brute-force grid steps per knob (reference cost)")
    p.add_argument("--report", default="", help="write full JSON here")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p.parse_args(argv)


def _fmt_recipe(r):
    return f"{r['pcr_cycles']} cyc, {r['input_ng']:.0f} ng, reagent {r['reagent_frac']:.2f}"


def main(argv=None) -> int:
    a = _parse(argv)
    s = ResponseSurface(seed=a.seed, fault_rate=a.fault_rate)
    true_x, true_cost = s.true_minimum(grid=a.grid)
    grid_runs = a.grid ** 3

    results = compare(budget=a.budget, seed=a.seed, fault_rate=a.fault_rate)
    honest = results["bo_honest"]

    print(f"\nPLANT: cheapest feasible recipe = {_fmt_recipe(to_real(true_x))}  (cost {true_cost:.3f})")
    print(f"       exhaustive search to find it = {grid_runs:,} runs\n")

    print(f"RECOVER (honest agent, {honest['runs']} runs):")
    if honest["found"]:
        print(f"  recipe   {_fmt_recipe(honest['rec_recipe'])}  (cost {honest['rec_cost']:.3f})")
        print(f"  feasible {honest['feasible']}   cost over true min {honest['cost_gap']:+.3f}"
              f"   distance {honest['distance']:.3f}")
    else:
        print("  no feasible recipe certified within budget")

    print("\nSTRATEGY COMPARISON (same budget + seed):")
    print(f"  {'strategy':<11}{'runs':>5}{'feasible':>10}{'rec_cost':>10}{'cost_gap':>10}")
    for k in ("bo_honest", "bo_naive", "random"):
        d = results[k]
        rc = f"{d['rec_cost']:.3f}" if d["rec_cost"] is not None else "-"
        cg = f"{d['cost_gap']:+.3f}" if d["cost_gap"] is not None else "-"
        print(f"  {k:<11}{d['runs']:>5}{str(d['feasible']):>10}{rc:>10}{cg:>10}")
    print("\n  honest vs naive is the CV-cleaning effect: keeping faulted wells makes a")
    print("  botched run look like a bad recipe, so the naive search lands costlier / less feasible.")
    print("  On this smooth 3-knob surface, space-filling (random) is a strong baseline;")
    print("  the point here is the closed loop and the fault handling, not beating random.\n")

    if a.report:
        with open(a.report, "w") as fh:
            json.dump({"plant": {"recipe": to_real(true_x), "cost": true_cost, "grid_runs": grid_runs},
                       "results": results}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
