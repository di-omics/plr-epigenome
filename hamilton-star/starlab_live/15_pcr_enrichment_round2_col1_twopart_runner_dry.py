import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

PCR2_MM_SCRIPT = ROOT / "13_pcr_enrichment_round2_col1_twopart_FROM_WORKING_MM.py"
PCR2_SAMPLE_SCRIPT = ROOT / "14_pcr_enrichment_round2_sample_col1_operator_volume_p10_FROM_WORKING_MM.py"


def run_step(label, cmd):
    print("")
    print("=" * 96)
    print(label)
    print("=" * 96)
    print(" ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="PCR enrichment round 2 column-1 two-part runner using operator-profile volumes."
    )
    parser.add_argument(
        "--mode",
        choices=["dry", "wet"],
        default="dry",
        help="dry returns tips, wet discards tips.",
    )
    parser.add_argument(
        "--p50-tip-col",
        type=int,
        default=2,
        help="1-indexed p50 tip column on rail48 pos1 for PCR2 MM transfer.",
    )
    parser.add_argument(
        "--p10-tip-col",
        type=int,
        default=1,
        help="1-indexed p10 tip column on rail48 pos0 for sample transfer.",
    )
    args = parser.parse_args()

    return_flag = ["--return-tips"] if args.mode == "dry" else []

    print("")
    print("PCR ENRICHMENT ROUND 2 COLUMN-1 TWO-PART RUNNER")
    print("")
    print("Deck assumptions:")
    print("  rail35 pos1 col3 A-H = PCR2 MM + i5/i7 primers")
    print("  rail35 pos1 col1 A-H = operator-staged PCR enrichment round 1 samples")
    print("  rail35 pos0 col1 A-H = destination PCR2 wells")
    print("  rail48 pos1 = p50 tips")
    print("  rail48 pos0 = p10 tips")
    print("")
    print("Order:")
    print("  1. Add the operator-prepared round 2 reagent with p50")
    print("  2. Add the operator-prepared sample with p10")
    print("")
    print(f"Mode: {args.mode}")
    print("")

    run_step(
        "STEP 1: round 2 reagent, operator volume, source col3 -> destination col1, p50",
        [
            sys.executable,
            str(PCR2_MM_SCRIPT),
            "--mode",
            "pcr2-mm",
            "--tip-col",
            str(args.p50_tip_col),
            *return_flag,
        ],
    )

    run_step(
        "STEP 2: operator-prepared sample, operator volume, source col1 -> destination col1, p10",
        [
            sys.executable,
            str(PCR2_SAMPLE_SCRIPT),
            "--mode",
            "pcr1-mm",
            "--tip-col",
            str(args.p10_tip_col),
            *return_flag,
        ],
    )

    print("")
    print("SUCCESS: PCR2 column-1 two-part runner completed.")
    print("")


if __name__ == "__main__":
    main()
