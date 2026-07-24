"""
CLI for the generic UMI library-workflow orchestrator.

The bundled profile is synthetic and simulation-only:

    python -m tipseq_plr.protocols.dna_library_umi.run --synthetic-profile

A live run requires an operator-reviewed JSON method:

    python -m tipseq_plr.protocols.dna_library_umi.run \
        --method-config /secure/local/method.json --no-simulate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import (
    DnaLibraryConfig,
    MethodConfigError,
    load_operator_method,
    synthetic_demo_method,
)
from .protocol import DnaLibraryUmi


def _parse(argv=None):
    p = argparse.ArgumentParser(
        description="Generic UMI library workflow on Hamilton STAR")
    p.add_argument("--samples", type=int, default=96)

    profile = p.add_mutually_exclusive_group(required=True)
    profile.add_argument(
        "--synthetic-profile",
        action="store_true",
        help="use arbitrary control-flow data; simulation only",
    )
    profile.add_argument(
        "--method-config",
        default="",
        metavar="JSON",
        help="operator-reviewed method file with all chemistry parameters",
    )
    p.add_argument(
        "--synthetic-size-selection",
        action="store_true",
        help="exercise the synthetic two-sided-selection branch",
    )

    p.add_argument("--vision", action="store_true",
                   help="enable in-process CV error handling")
    p.add_argument("--vision-monitor", action="store_true",
                   help="with --vision: log CV faults but do not abort")
    p.add_argument("--vision-fault-at", default="",
                   help="inject a named synthetic CV fault")

    sim = p.add_mutually_exclusive_group()
    sim.add_argument("--simulate", dest="simulate", action="store_true", default=True)
    sim.add_argument("--no-simulate", dest="simulate", action="store_false")
    p.add_argument("--report", default="", help="write the full JSON report here")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p.parse_args(argv)


async def _amain(a) -> int:
    if a.synthetic_size_selection and not a.synthetic_profile:
        raise MethodConfigError(
            "--synthetic-size-selection can only be used with --synthetic-profile")

    method = (
        synthetic_demo_method(size_selection=a.synthetic_size_selection)
        if a.synthetic_profile
        else load_operator_method(a.method_config)
    )
    cfg = DnaLibraryConfig(
        method=method,
        num_samples=a.samples,
        simulate=a.simulate,
        vision_enabled=a.vision,
        vision_abort_on_fault=not a.vision_monitor,
        vision_fault_at=tuple(x for x in [a.vision_fault_at] if x),
    )
    setattr(cfg, "_sim_time_scale", 0.0)

    report = await DnaLibraryUmi(cfg).run()
    print(json.dumps({
        "status": report.get("status"),
        "method_profile": report.get("method_profile"),
        "validation_tier": report.get("validation_tier"),
        "pcr_cycles": report.get("pcr_cycles"),
        "counts": report["counts"],
        "vision_faults": report.get("vision_faults"),
        "vision_fault": report.get("vision_fault"),
        "fragment_analysis": report.get("fragment_analysis"),
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
        format="%(asctime)s %(name)-20s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        return asyncio.run(_amain(a))
    except MethodConfigError as exc:
        logging.getLogger("tipseq").error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
