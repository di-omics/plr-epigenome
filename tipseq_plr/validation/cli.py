"""
CLI for the liquid-test validation framework.

    # show the public confidence ladder (all protocols start UNTESTED)
    python -m tipseq_plr.validation.cli status

    # evaluate a Rhodamine B dataset against the success criteria
    python -m tipseq_plr.validation.cli evaluate --data rhodamine_run.json

The dataset JSON is the paired plate-reader data from a real STAR run:

    {
      "standards": [{"volume_ul": 2, "rfu": 1900}, {"volume_ul": 20, "rfu": 19000}, ...],
      "readings":  [{"well": "A1", "target_ul": 10, "rfu": 9600}, ...]
    }

A protocol is promoted to LIQUID_TESTED only when this returns liquid_tested=true.
Biological-result validation is recorded in the configured laboratory results system.
"""

from __future__ import annotations

import argparse
import json
import sys

from .rhodamine import Reading, RhodamineCriteria, Standard, evaluate
from .status import BIOLOGY_RECORDS_LOCATION, status_table


def cmd_status(a):
    print(status_table())
    print(f"\nbiology records: {BIOLOGY_RECORDS_LOCATION}")


def cmd_evaluate(a):
    with open(a.data) as fh:
        d = json.load(fh)
    standards = [Standard(volume_ul=s["volume_ul"], rfu=s["rfu"]) for s in d["standards"]]
    readings = [Reading(well=r.get("well", "?"), target_ul=r["target_ul"], rfu=r["rfu"])
                for r in d["readings"]]
    crit = RhodamineCriteria()
    if "criteria" in d:
        for k, v in d["criteria"].items():
            if hasattr(crit, k):
                setattr(crit, k, v)
    report = evaluate(standards, readings, crit)
    print(json.dumps(report, indent=2))
    if a.report:
        with open(a.report, "w") as fh:
            json.dump(report, fh, indent=2)
    # non-zero exit if the bar was not cleared, so CI can gate on it
    return 0 if report["liquid_tested"] else 1


def build_parser():
    p = argparse.ArgumentParser(prog="validation", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status"); st.set_defaults(fn=cmd_status)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--data", required=True, help="paired Rhodamine B dataset JSON")
    ev.add_argument("--report", default="", help="write the verdict JSON here")
    ev.set_defaults(fn=cmd_evaluate)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
