import argparse
import subprocess
import sys
from pathlib import Path


# The nested validation copy orchestrates the complete live-script set.
ROOT = Path(__file__).resolve().parents[3]

MM_SCRIPT = ROOT / "04_pcr_enrichment_96wp_pcr1_pcr2_mastermix_DSPH15_DRY.py"
ISWAP_TO_MAG_SCRIPT = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
CLEANUP_SCRIPT = ROOT / "02_pcr_enrichment_round1_cleanup_col1_dry_v2_p50low.py"
ISWAP_TO_POS0_SCRIPT = ROOT / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"


def run_step(label, cmd):
    print("")
    print("=" * 88)
    print(label)
    print("=" * 88)
    print(" ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "FULL PCR enrichment built dry choreography: PCR1 MM -> iSWAP to mag -> "
            "PCR1 cleanup all-dry -> iSWAP back -> PCR2 MM."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["full-built-dry"],
        default="full-built-dry",
    )
    parser.add_argument(
        "--return-tips",
        action="store_true",
        default=True,
        help="Dry mode default: return tips for MM and cleanup. Wet/mock should use a separate discard-tip wrapper.",
    )
    parser.add_argument(
        "--pause-after-pcr1-mm",
        action="store_true",
        help="Pause after PCR1 MM to represent off-deck thermocycler / manual inspection timing.",
    )
    parser.add_argument(
        "--pause-after-cleanup",
        action="store_true",
        help="Pause after cleanup return before PCR2 MM setup.",
    )
    args = parser.parse_args()

    print("")
    print("FULL PCR ENRICHMENT BUILT DRY CHOREOGRAPHY")
    print("")
    print("Assumptions:")
    print("  rail35 pos0 = work/destination plate")
    print("  rail35 pos1 = source 96WP")
    print("    col1 = PCR1 MM source")
    print("    col3 = PCR2 MM source")
    print("  rail35 pos2 = empty raised magnetic block before iSWAP")
    print("  rail35 pos3 = 12-well reservoir/waste")
    print("  rail48 pos1 = p50 tips")
    print("  rail48 pos2 = p300/p1000-class tips")
    print("")
    print("Dry choreography only. Real wet protocol uses the operator-approved local SOP and thermal program.")
    print("")

    run_step(
        "STEP 1: PCR1 master mix dry add at rail35 pos0",
        [
            sys.executable,
            str(MM_SCRIPT),
            "--mode",
            "pcr1-mm",
            "--return-tips",
            "--tip-col",
            "1",
        ],
    )

    if args.pause_after_pcr1_mm:
        input(
            "\nPAUSE after PCR1 MM. Follow the operator-approved local SOP/program now. "
            "Press Enter to continue to iSWAP cleanup..."
        )

    run_step(
        "STEP 2: iSWAP plate rail35 pos0 -> rail35 pos2 magnetic block",
        [
            sys.executable,
            str(ISWAP_TO_MAG_SCRIPT),
            "--mode",
            "move",
            "--confirm",
            "RUN_ISWAP_MAG_MOVE_TEST",
        ],
    )

    run_step(
        "STEP 3: PCR1 cleanup column-1 all-dry on rail35 pos2",
        [
            sys.executable,
            str(CLEANUP_SCRIPT),
            "--mode",
            "all-dry",
        ],
    )

    run_step(
        "STEP 4: iSWAP plate rail35 pos2 magnetic block -> rail35 pos0",
        [
            sys.executable,
            str(ISWAP_TO_POS0_SCRIPT),
            "--mode",
            "move",
            "--pickup-z-offset-mm",
            "14.0",
            "--drop-z-offset-mm",
            "8.5",
            "--confirm",
            "RUN_ISWAP_MAG_RETURN_TEST",
        ],
    )

    if args.pause_after_cleanup:
        input(
            "\nPAUSE after cleanup return. Follow the operator-approved local SOP for round 2 setup now. "
            "Press Enter to continue to PCR2 MM..."
        )

    run_step(
        "STEP 5: PCR2 common master mix dry add at rail35 pos0",
        [
            sys.executable,
            str(MM_SCRIPT),
            "--mode",
            "pcr2-mm",
            "--return-tips",
            "--tip-col",
            "2",
        ],
    )

    print("")
    print("SUCCESS: FULL PCR enrichment built dry choreography completed.")
    print("")


if __name__ == "__main__":
    main()
