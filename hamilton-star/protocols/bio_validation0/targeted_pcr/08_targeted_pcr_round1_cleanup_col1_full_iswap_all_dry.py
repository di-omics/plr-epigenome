import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

ISWAP_TO_MAG_SCRIPT = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
ISWAP_TO_POS0_SCRIPT = ROOT / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"
CLEANUP_SCRIPT = ROOT / "02_targeted_pcr_round1_cleanup_col1_dry_v2_p50low.py"


def run_step(label, cmd):
    print("")
    print("=" * 80)
    print(label)
    print("=" * 80)
    print(" ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Targeted PCR round 1 cleanup full dry wrapper: iSWAP pos0 -> mag, cleanup all-dry, iSWAP mag -> pos0."
    )
    parser.add_argument(
        "--mode",
        choices=["full-iswap-cleanup-all-dry"],
        default="full-iswap-cleanup-all-dry",
    )
    parser.add_argument(
        "--discard-tips",
        action="store_true",
        help="Pass through to cleanup script. For dry tuning, omit so tips return.",
    )
    args = parser.parse_args()

    run_step(
        "STEP 1: iSWAP plate rail35 pos0 -> rail35 pos2 magnetic block",
        [
            sys.executable,
            str(ISWAP_TO_MAG_SCRIPT),
            "--mode",
            "move",
            "--confirm",
            "RUN_ISWAP_MAG_MOVE_TEST",
        ],
    )

    cleanup_cmd = [
        sys.executable,
        str(CLEANUP_SCRIPT),
        "--mode",
        "all-dry",
    ]
    if args.discard_tips:
        cleanup_cmd.append("--discard-tips")

    run_step(
        "STEP 2: PCR1 cleanup column-1 all-dry on rail35 pos2",
        cleanup_cmd,
    )

    run_step(
        "STEP 3: iSWAP plate rail35 pos2 magnetic block -> rail35 pos0",
        [
            sys.executable,
            str(ISWAP_TO_POS0_SCRIPT),
            "--mode",
            "move",
            "--confirm",
            "RUN_ISWAP_MAG_RETURN_TEST",
        ],
    )

    print("")
    print("SUCCESS: full targeted PCR round 1 cleanup iSWAP all-dry workflow completed.")


if __name__ == "__main__":
    main()
