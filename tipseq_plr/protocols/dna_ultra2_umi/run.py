"""
CLI for the end-to-end NEBNext Ultra II DNA + UMI protocol.

    # 96 libraries from 100 ng input, cleanup path, dry run with logs
    python -m tipseq_plr.protocols.dna_ultra2_umi.run --samples 96 --input-ng 100 --simulate -v

    # two-sided size selection for a 300 bp insert, write the full report
    python -m tipseq_plr.protocols.dna_ultra2_umi.run --size-select --insert-bp 300 --report ultra2.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import Ultra2Config
from .protocol import Ultra2DnaUmi


def _parse(argv=None):
    p = argparse.ArgumentParser(
        description="NEBNext Ultra II DNA (UMI) end-to-end library prep on Hamilton STAR")
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--input-ng", type=float, default=100.0, help="per-sample fragmented DNA input (ng)")
    p.add_argument("--size-select", action="store_true",
                   help="two-sided SPRI size selection instead of the 0.7X cleanup")
    p.add_argument("--insert-bp", type=int, default=150, help="target insert size for size selection")
    p.add_argument("--cycles", type=int, default=0, help="override PCR cycles (0 = derive from input)")
    p.add_argument("--vision", action="store_true",
                   help="in-process CV error handling at the SPRI/tip steps (reader-blind failures)")
    p.add_argument("--vision-monitor", action="store_true",
                   help="with --vision: log CV faults but do not abort (monitor only)")
    p.add_argument("--vision-fault-at", default="",
                   help="inject a fault at this checkpoint, e.g. bead_pellet_formed (demo/testing)")
    sim = p.add_mutually_exclusive_group()
    sim.add_argument("--simulate", dest="simulate", action="store_true", default=True)
    sim.add_argument("--no-simulate", dest="simulate", action="store_false")
    p.add_argument("--report", default="", help="write the full JSON report here")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p.parse_args(argv)


async def _amain(a) -> int:
    cfg = Ultra2Config(
        num_samples=a.samples, input_ng=a.input_ng, size_select=a.size_select,
        pcr_cycles_override=a.cycles, simulate=a.simulate,
        vision_enabled=a.vision, vision_abort_on_fault=not a.vision_monitor,
        vision_fault_at=tuple(x for x in [a.vision_fault_at] if x),
    )
    cfg.sizeselect.insert_bp = a.insert_bp
    setattr(cfg, "_sim_time_scale", 0.0)

    report = await Ultra2DnaUmi(cfg).run()

    print(json.dumps({
        "status": report.get("status"),
        "validation_tier": report.get("validation_tier"),
        "pcr_cycles": report.get("pcr_cycles"),
        "counts": report["counts"],
        "vision_faults": report.get("vision_faults"),
        "vision_fault": report.get("vision_fault"),
        "tapestation": report.get("tapestation"),
        "pool_plan_head": report["pool_plan"][:8],
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
        format="%(asctime)s %(name)-20s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    return asyncio.run(_amain(a))


if __name__ == "__main__":
    sys.exit(main())
