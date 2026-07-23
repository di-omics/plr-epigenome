import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

MM_SCRIPT = ROOT / "04_targeted_pcr_96wp_pcr1_pcr2_mastermix_DSPH15_DRY.py"
ISWAP_TO_MAG_SCRIPT = ROOT / "test_iswap_plate_rail35pos0_to_rail35pos2_mag_variable.py"
CLEANUP_SCRIPT = ROOT / "02_targeted_pcr_round1_cleanup_col1_dry_v2_p50low.py"
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
            "Targeted PCR V2 protocol runner. Runs all currently built Hamilton liquid-handling "
            "steps in protocol order, with pauses for thermocycling, gels, indexing decisions, "
            "pooling, and final off-deck QC."
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
    print("TARGETED PCR V2 PROTOCOL RUNNER")
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
    print("      A1 = SPRI beads / bead mimic")
    print("      A2 = 80% EtOH wash 1 / mimic")
    print("      A3 = 80% EtOH wash 2 / mimic")
    print("      A4 = elution H2O / mimic")
    print("      A12 = waste")
    print("  rail48 pos1 = p50 tips")
    print("  rail48 pos2 = p300/p1000-class tips")
    print("")
    print(f"Mode: {args.mode}")
    print("  dry = return tips where supported")
    print("  wet = discard tips where supported")
    print("")
    print("Not yet automated on Hamilton:")
    print("  template loading, thermocycling, gel checks, unique i5/i7 distribution,")
    print("  diluted PCR1 product transfer into PCR2, final pooled tube cleanup, Qubit/nM.")
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
            "Load template DNA/control into rail35 pos0 PCR plate before PCR1 MM add.\n"
            "PCR1 robot add assumes template volume is already present, <=2.5 uL.",
            pauses,
        )

        run_step(
            "STEP 1: Hamilton PCR1 complete master-mix add",
            pcr1_mm_cmd,
        )

    pause(
        "OFF-DECK PCR1 THERMOCYCLING\n"
        "Run PCR1 cycling:\n"
        "  98C 30s\n"
        "  30x: 98C 10s, 67C 15s, 72C 15s\n"
        "  72C 1min\n"
        "  10C hold\n"
        "Then return plate to rail35 pos0 for cleanup.",
        pauses,
    )

    if not args.skip_pcr1_cleanup:
        pause(
            "PRE-CLEANUP CHECK\n"
            "Start state required:\n"
            "  rail35 pos0 = PCR1 plate\n"
            "  rail35 pos2 = empty magnetic block\n"
            "  rail35 pos3 reservoir loaded A1 beads, A2 EtOH1, A3 EtOH2, A4 H2O, A12 waste.",
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
            "STEP 3: Hamilton PCR1 0.9X bead cleanup",
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
        "POST-PCR1 CLEANUP / PRE-PCR2 CHECKPOINT\n"
        "Manual/off-deck protocol work here:\n"
        "  1. Confirm PCR1 cleanup result as desired.\n"
        "  2. Dilute bead-cleaned PCR1 product 1:4 as needed.\n"
        "  3. Optional 2% SYBR e-gel checkpoint.\n"
        "  4. Load PCR2 plate/wells with sample-specific i5 + i7 + diluted PCR1 product.\n"
        "PCR2 common MM add assumes i5+i7+product are already in destination wells.",
        pauses,
    )

    if not args.skip_pcr2_mm:
        run_step(
            "STEP 5: Hamilton PCR2 common master-mix add",
            pcr2_mm_cmd,
        )

    pause(
        "OFF-DECK PCR2 THERMOCYCLING AND FINISHING\n"
        "Run PCR2 cycling:\n"
        "  98C 30s\n"
        "  8-10x: 98C 10s, 67C 15s, 72C 15s\n"
        "  72C 1min\n"
        "  4C hold\n\n"
        "Then manual/off-deck:\n"
        "  run 3 uL PCR2 product on 2% SYBR e-gel\n"
        "  pool products\n"
        "  final pooled 0.65X SPRI cleanup\n"
        "  Qubit, optional e-gel, nM calculation.",
        pauses,
    )

    print("")
    print("SUCCESS: Targeted PCR V2 protocol runner completed all currently built Hamilton LH steps.")
    print("")


if __name__ == "__main__":
    main()
