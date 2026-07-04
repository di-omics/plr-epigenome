"""
CLI for the plate-normalization protocol.

    # normalize 96 wells to 1 ng/uL in 20 uL, from a 12 uL source plate (dry run)
    python -m tipseq_plr.protocols.normalization.run --samples 96 --target 1.0 --final 20 --simulate -v

    # just the concentrations + transfer plan as JSON
    python -m tipseq_plr.protocols.normalization.run --report norm.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import NormConfig
from .protocol import PlateNormalization


def _parse(argv=None):
    p = argparse.ArgumentParser(description="Qubit HS quant + 96-well normalization on Hamilton STAR")
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--source-volume", type=float, default=12.0, help="uL per source well")
    p.add_argument("--target", type=float, default=1.0, help="target ng/uL")
    p.add_argument("--final", type=float, default=20.0, help="final volume uL per dest well")
    p.add_argument("--aliquot", type=float, default=2.0, help="Qubit sample aliquot uL")
    sim = p.add_mutually_exclusive_group()
    sim.add_argument("--simulate", dest="simulate", action="store_true", default=True)
    sim.add_argument("--no-simulate", dest="simulate", action="store_false")
    p.add_argument("--report", default="", help="write full JSON report here")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p.parse_args(argv)


async def _amain(a) -> int:
    cfg = NormConfig(
        num_samples=a.samples,
        source_volume_ul=a.source_volume,
        target_ng_per_ul=a.target,
        final_volume_ul=a.final,
        simulate=a.simulate,
    )
    cfg.qubit.sample_aliquot_ul = a.aliquot
    setattr(cfg, "_sim_time_scale", 0.0)

    report = await PlateNormalization(cfg).run()

    print(json.dumps({
        "target_ng_per_ul": report["target_ng_per_ul"],
        "final_volume_ul": report["final_volume_ul"],
        "wells": report["wells"],
        "counts": report["counts"],
        "total_sample_ul": report["total_sample_ul"],
        "total_water_ul": report["total_water_ul"],
    }, indent=2))
    if a.report:
        with open(a.report, "w") as fh:
            json.dump(report, fh, indent=2)
        logging.getLogger("tipseq").info("wrote report -> %s", a.report)
    return 0


def main(argv=None) -> int:
    a = _parse(argv)
    logging.basicConfig(
        level=logging.INFO if a.verbose else logging.WARNING,
        format="%(asctime)s %(name)-18s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    return asyncio.run(_amain(a))


if __name__ == "__main__":
    sys.exit(main())
