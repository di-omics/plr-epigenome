"""
Minimal programmatic run (simulation) of the fully-autonomous plate TIP-seq.

    python examples/run_plate_tipseq.py

Shows the two things you'd do from a notebook: print the prep sheet, then run
the protocol and inspect the QC report.
"""

import asyncio
import json
import logging

from tipseq_plr import Method, RunConfig, TipSeqProtocol


async def main():
    logging.basicConfig(level=logging.INFO, format="%(name)-16s %(message)s")

    cfg = RunConfig(
        method=Method.PLATE_TIPSEQ,
        num_samples=96,
        antibody_targets=("H3K27me3", "H3K27ac", "H3K9me3", "CTCF", "RNAPII-S2P"),
        simulate=True,
        ivt_hours=17.0,
        pcr_cycles=9,
    )
    setattr(cfg, "_sim_time_scale", 0.0)  # instant sleeps

    proto = TipSeqProtocol(cfg)

    print("\n=== reagent prep sheet ===")
    print(json.dumps(proto.loadout()["reagents"], indent=2))

    print("\n=== running protocol ===")
    report = await proto.run()

    print("\n=== QC summary ===")
    print(json.dumps(report["counts"], indent=2))
    worst = sorted(report["wells"], key=lambda w: w["ng_per_ul"])[:5]
    print("lowest-yield wells:", [(w["well"], w["ng_per_ul"]) for w in worst])


if __name__ == "__main__":
    asyncio.run(main())
