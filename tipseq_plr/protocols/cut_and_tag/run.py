"""
CLI for automated CUT&Tag.

    # dry-run CUT&Tag for 96 samples end to end
    python -m tipseq_plr.protocols.cut_and_tag.run --samples 96 --simulate -v

    # write the QC report
    python -m tipseq_plr.protocols.cut_and_tag.run --report cutandtag.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import CutAndTagConfig
from .protocol import CutAndTag


def _parse(argv=None):
    p = argparse.ArgumentParser(description="Automated CUT&Tag on Hamilton STAR")
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--pcr-cycles", type=int, default=14)
    sim = p.add_mutually_exclusive_group()
    sim.add_argument("--simulate", dest="simulate", action="store_true", default=True)
    sim.add_argument("--no-simulate", dest="simulate", action="store_false")
    p.add_argument("--report", default="")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p.parse_args(argv)


async def _amain(a) -> int:
    cfg = CutAndTagConfig(num_samples=a.samples, pcr_cycles=a.pcr_cycles, simulate=a.simulate)
    setattr(cfg, "_sim_time_scale", 0.0)
    report = await CutAndTag(cfg).run()
    print(json.dumps({"method": report["method"], "samples": report["samples"],
                      "counts": report["counts"]}, indent=2))
    if a.report:
        with open(a.report, "w") as fh:
            json.dump(report, fh, indent=2)
        logging.getLogger("tipseq").info("wrote report -> %s", a.report)
    return 0


def main(argv=None) -> int:
    a = _parse(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(name)-18s %(levelname)-7s %(message)s")
    return asyncio.run(_amain(a))


if __name__ == "__main__":
    sys.exit(main())
