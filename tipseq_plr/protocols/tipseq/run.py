"""
Command-line entry point.

    # dry-run the fully-autonomous plate TIP-seq for 96 samples
    python -m tipseq_plr.protocols.tipseq.run --method plate_tipseq --samples 96 --simulate

    # sciTIP-seq dry-run (prints the FACS handoff, then continues)
    python -m tipseq_plr.protocols.tipseq.run --method scitip_seq --samples 96 --simulate

    # print the reagent loadout / labware checklist only
    python -m tipseq_plr.protocols.tipseq.run --plan-only

Use --sim-time-scale to actually feel the timing (0.0 = instant; 1e-4 compresses
17 h of IVT into ~6 s). Real hardware: drop --simulate and set device addresses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from ...config import Method, RunConfig
from .protocol import TipSeqProtocol


def _parse(argv=None):
    p = argparse.ArgumentParser(description="Automated (sci)TIP-seq on Hamilton STAR")
    p.add_argument("--method", choices=[m.value for m in Method],
                   default=Method.PLATE_TIPSEQ.value)
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--ivt-hours", type=float, default=17.0)
    p.add_argument("--pcr-cycles", type=int, default=9)
    sim = p.add_mutually_exclusive_group()
    sim.add_argument("--simulate", dest="simulate", action="store_true", default=True)
    sim.add_argument("--no-simulate", dest="simulate", action="store_false")
    p.add_argument("--sim-time-scale", type=float, default=0.0,
                   help="fraction of real time to sleep in simulation (0=instant)")
    p.add_argument("--plan-only", action="store_true",
                   help="print reagent loadout + labware checklist and exit")
    p.add_argument("--report", type=str, default="",
                   help="write the QC report JSON to this path")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p.parse_args(argv)


def _build_config(args) -> RunConfig:
    cfg = RunConfig(
        method=Method(args.method),
        num_samples=args.samples,
        simulate=args.simulate,
        ivt_hours=args.ivt_hours,
        pcr_cycles=args.pcr_cycles,
    )
    # runtime-only knob consumed by devices._sleep
    setattr(cfg, "_sim_time_scale", args.sim_time_scale)
    return cfg


async def _amain(args) -> int:
    cfg = _build_config(args)
    proto = TipSeqProtocol(cfg)

    if args.plan_only:
        print(json.dumps(proto.loadout(), indent=2))
        return 0

    # always print the loadout header, then run
    logging.getLogger("tipseq").info("loadout:\n%s", json.dumps(proto.loadout(), indent=2))
    report = await proto.run()

    print(json.dumps(report["counts"], indent=2))
    if args.report:
        with open(args.report, "w") as fh:
            json.dump(report, fh, indent=2)
        logging.getLogger("tipseq").info("wrote report -> %s", args.report)
    return 0


def main(argv=None) -> int:
    args = _parse(argv)
    level = logging.WARNING - min(args.verbose, 2) * 10  # -v INFO, -vv DEBUG
    logging.basicConfig(
        level=level if args.verbose else logging.INFO,
        format="%(asctime)s %(name)-18s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
