import argparse
import subprocess
import sys
from pathlib import Path

from pathlib import Path as _MethodPath
import sys as _method_sys

_method_root = next(parent for parent in _MethodPath(__file__).resolve().parents if parent.name == "hamilton-star")
if str(_method_root) not in _method_sys.path:
    _method_sys.path.insert(0, str(_method_root))
from operator_parameters import required_positive, required_nonnegative, required_text


ROOT = Path(__file__).resolve().parent
THERMAL_PROGRAM_ID = required_text("pcr_enrichment.thermal_program_id")

MM_SCRIPT = ROOT / "04_pcr_enrichment_96wp_pcr1_pcr2_mastermix_DSPH15_DRY.py"
ISWAP_TO_MAG_SCRIPT = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
CLEANUP_SCRIPT = ROOT / "02_pcr_enrichment_round1_cleanup_col1_dry_v2_p50low.py"
ISWAP_TO_POS0_SCRIPT = ROOT / "test_iswap_plate_rail35pos2_mag_to_rail35pos0_variable.py"


def run_step(label, cmd):
    print("")
    print("=" * 96)
    print(label)
    print("=" * 96)
    print(" ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def pause(label, enabled=True):
    if not enabled:
        return
    print("")
    print("-" * 96)
    print(label)
    print("-" * 96)
    input("Press Enter to continue...")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "PCR enrichment protocol runner. Runs the built Hamilton liquid-handling "
            "steps with operator-approved local SOP handoffs."
        )
    )

    parser.add_argument(
        "--mode",
        choices=["dry", "wet"],
        default="dry",
        help="dry returns tips where supported; wet discards tips where supported.",
    )
    parser.add_argument(
        "--no-pauses",
        action="store_true",
        help="Skip protocol pauses. Mostly useful for pure dry choreography testing.",
    )
    parser.add_argument(
        "--skip-pcr1-mm",
        action="store_true",
        help="Skip PCR1 master-mix addition.",
    )
    parser.add_argument(
        "--skip-pcr1-cleanup",
        action="store_true",
        help="Skip PCR1 bead cleanup.",
    )
    parser.add_argument(
        "--skip-pcr2-mm",
        action="store_true",
        help="Skip PCR2 common master-mix addition.",
    )

    args = parser.parse_args()

    pauses = not args.no_pauses
    wet = args.mode == "wet"

    print("")
    print("PCR ENRICHMENT PROTOCOL RUNNER")
    print("")
    print("This runs all currently built Hamilton-doable liquid handling in SOP order.")
    print("")
    print("Deck assumptions:")
    print("  rail35 pos0 = work/PCR plate")
    print("  rail35 pos1 = source 96WP")
    print("      col1 = PCR1 complete master mix")
    print("      col3 = PCR2 common master mix")
    print("  rail35 pos2 = raised magnetic block, empty before cleanup")
    print("  rail35 pos3 = reservoir/waste")
    print("      cleanup reagents and waste staged per the operator-approved local SOP")
    print("  rail48 pos1 = p50 tips")
    print("  rail48 pos2 = p300/p1000-class tips")
    print("")
    print(f"Mode: {args.mode}")
    print("  dry = return tips where supported")
    print("  wet = discard tips where supported")
    print("")
    print("Off-deck method details are controlled by the operator-approved local SOP.")
    print("")

    pcr1_mm_cmd = [
        sys.executable,
        str(MM_SCRIPT),
        "--mode",
        "pcr1-mm",
        "--tip-col",
        "1",
    ]
    if not wet:
        pcr1_mm_cmd.append("--return-tips")

    pcr2_mm_cmd = [
        sys.executable,
        str(MM_SCRIPT),
        "--mode",
        "pcr2-mm",
        "--tip-col",
        "2",
    ]
    if not wet:
        pcr2_mm_cmd.append("--return-tips")

    cleanup_cmd = [
        sys.executable,
        str(CLEANUP_SCRIPT),
        "--mode",
        "all-dry",
    ]
    if wet:
        cleanup_cmd.append("--discard-tips")

    if not args.skip_pcr1_mm:
        pause(
            "PRE-PCR1 SETUP CHECK\n"
            "Prepare rail35 pos0 and the round 1 source according to the approved local SOP.",
            pauses,
        )

        run_step(
            "STEP 1: Hamilton PCR1 complete master-mix add",
            pcr1_mm_cmd,
        )

    pause(
        "OFF-DECK ROUND 1 HANDOFF\n"
        f"Run operator-approved program {THERMAL_PROGRAM_ID}, then return the plate "
        "to rail35 pos0 for the next approved step.",
        pauses,
    )

    if not args.skip_pcr1_cleanup:
        pause(
            "PRE-CLEANUP CHECK\n"
            "Start state required:\n"
            "  rail35 pos0 = PCR1 plate\n"
            "  rail35 pos2 = empty magnetic block\n"
            "  rail35 pos3 reservoir loaded per the operator-approved local SOP.",
            pauses,
        )

        run_step(
            "STEP 2: iSWAP PCR1 plate rail35 pos0 -> rail35 pos2 magnetic block",
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
            "STEP 3: Hamilton operator-configured round 1 cleanup",
            cleanup_cmd,
        )

        run_step(
            "STEP 4: iSWAP PCR1 cleanup plate rail35 pos2 magnetic block -> rail35 pos0",
            [
                sys.executable,
                str(ISWAP_TO_POS0_SCRIPT),
                "--mode",
                "move",
                "--confirm",
                "RUN_ISWAP_MAG_RETURN_TEST",
            ],
        )

    pause(
        "POST-ROUND 1 / PRE-ROUND 2 CHECKPOINT\n"
        "Perform the operator-approved local SOP handoff and prepare the round 2 "
        "destination/source wells before continuing.",
        pauses,
    )

    if not args.skip_pcr2_mm:
        run_step(
            "STEP 5: Hamilton PCR2 common master-mix add",
            pcr2_mm_cmd,
        )

    pause(
        "OFF-DECK ROUND 2 AND FINISHING HANDOFF\n"
        f"Run operator-approved program {THERMAL_PROGRAM_ID}, then complete all "
        "remaining work and acceptance checks according to the approved local SOP.",
        pauses,
    )

    print("")
    print("SUCCESS: PCR enrichment protocol runner completed all currently built Hamilton LH steps.")
    print("")


if __name__ == "__main__":
    main()
