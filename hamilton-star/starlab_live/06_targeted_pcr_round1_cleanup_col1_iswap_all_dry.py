import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

ISWAP_SCRIPT = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
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
        description="Targeted PCR round 1 cleanup integrated dry wrapper: iSWAP rail35 pos0 -> pos2 mag, then cleanup all-dry."
    )
    parser.add_argument(
        "--mode",
        choices=["iswap-only", "cleanup-all-dry", "iswap-cleanup-all-dry"],
        default="iswap-cleanup-all-dry",
    )
    parser.add_argument(
        "--discard-tips",
        action="store_true",
        help="Pass through to cleanup script. For dry tuning, omit this so tips return.",
    )
    args = parser.parse_args()

    if args.mode in {"iswap-only", "iswap-cleanup-all-dry"}:
        run_step(
            "STEP 1: iSWAP plate rail35 pos0 -> rail35 pos2 magnetic block",
            [
                sys.executable,
                str(ISWAP_SCRIPT),
                "--mode",
                "move",
                "--confirm",
                "RUN_ISWAP_MAG_MOVE_TEST",
            ],
        )

    if args.mode in {"cleanup-all-dry", "iswap-cleanup-all-dry"}:
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

    print("")
    print("SUCCESS: integrated targeted PCR round 1 cleanup dry wrapper completed.")


if __name__ == "__main__":
    main()
