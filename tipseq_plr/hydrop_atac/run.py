"""
CLI for the HyDrop scATAC + Onyx workflow.

    # dry-run 8 HyDrop samples end to end (STAR -> arm -> Onyx -> arm -> STAR)
    python -m tipseq_plr.hydrop_atac.run --samples 8 --simulate -v

    # write the QC report
    python -m tipseq_plr.hydrop_atac.run --report hydrop.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import HyDropConfig
from .protocol import HyDropATAC


def _parse(argv=None):
    p = argparse.ArgumentParser(description="HyDrop scATAC on Hamilton STAR + Onyx droplet gen")
    p.add_argument("--samples", type=int, default=8)
    p.add_argument("--nuclei", type=int, default=25000, help="nuclei per tagmentation")
    sim = p.add_mutually_exclusive_group()
    sim.add_argument("--simulate", dest="simulate", action="store_true", default=True)
    sim.add_argument("--no-simulate", dest="simulate", action="store_false")
    p.add_argument("--report", default="")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p.parse_args(argv)


async def _amain(a) -> int:
    cfg = HyDropConfig(num_samples=a.samples, nuclei_per_reaction=a.nuclei, simulate=a.simulate)
    setattr(cfg, "_sim_time_scale", 0.0)
    report = await HyDropATAC(cfg).run()
    print(json.dumps({k: report[k] for k in ("samples", "libraries", "pass", "emulsion_ul")},
                     indent=2))
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
