"""Full PTA/HHS iSWAP + targeted PCR dry choreography runner (Bio Validation 0).

Dry / camera choreography only. This orchestrates three already-validated
scripts as subprocesses; it does NOT define or change any liquid-handling or
iSWAP geometry itself. Offsets below are the values confirmed on the live instrument
testing (see ../pta_wga/ISWAP_HHS_RAIL27_POS2_TUNING.md).

Phases:
  1. PTA/HHS iSWAP forward move: rail35 pos0 -> rail27 pos2 (HHS)
  2. PTA/HHS iSWAP return move:  rail27 pos2 (HHS) -> rail35 pos0
  3. targeted PCR full built dry choreography (09_targeted_pcr_full_built_end_to_end_dry.py)

Refuses to run without: --confirm RUN_FULL_PTA_TARGETED_PCR_DRY_RETURN_TIPS
Use an EMPTY sacrificial plate. Destination nests must be physically empty.
Keep a hand near the E-stop.
"""

import argparse
import subprocess
import sys
from pathlib import Path


CONFIRM_TOKEN = "RUN_FULL_PTA_TARGETED_PCR_DRY_RETURN_TIPS"

# repo root: .../protocols/bio_validation0/full_end_to_end/<this file>
ROOT = Path(__file__).resolve().parents[3]
PTA_DIR = ROOT / "protocols" / "bio_validation0" / "pta_wga"
TARGETED_PCR_DIR = ROOT / "protocols" / "bio_validation0" / "targeted_pcr"

FORWARD_SCRIPT = PTA_DIR / "test_iswap_plate_rail35pos0_to_rail27_variable.py"
RETURN_SCRIPT = PTA_DIR / "test_iswap_plate_rail27pos2_hhs_to_rail35pos0_return.py"
TARGETED_PCR_SCRIPT = TARGETED_PCR_DIR / "09_targeted_pcr_full_built_end_to_end_dry.py"

# Validated forward move: rail35 pos0 -> rail27 pos2 (HHS).
FORWARD_CMD = [
    sys.executable,
    str(FORWARD_SCRIPT),
    "--mode", "move",
    "--drop-position", "2",
    "--pickup-z-offset-mm", "5.5",
    "--drop-x-offset-mm", "12.0",
    "--drop-y-offset-mm", "54.5",
    "--drop-z-offset-mm", "17.0",
    "--confirm", "RUN_ISWAP_PLATE_TEST",
]

# Validated return move: rail27 pos2 (HHS) -> rail35 pos0.
# The return script's built-in defaults are not the validated values, so the
# tuned offsets are passed explicitly here.
RETURN_CMD = [
    sys.executable,
    str(RETURN_SCRIPT),
    "--hhs-pickup-x-offset-mm", "12.0",
    "--hhs-pickup-y-offset-mm", "54.5",
    "--hhs-pickup-z-offset-mm", "9.0",
    "--return-drop-z-offset-mm", "8.5",
]

# targeted PCR full built dry choreography (returns tips; not a discard-tip run).
TARGETED_PCR_CMD = [
    sys.executable,
    str(TARGETED_PCR_SCRIPT),
]


def banner(phase_num, title):
    print("")
    print("=" * 88)
    print(f"PHASE {phase_num}: {title}")
    print("=" * 88)


def run_phase(phase_num, title, cmd):
    banner(phase_num, title)
    print(" ".join(str(x) for x in cmd))
    print("")
    subprocess.run(cmd, cwd=ROOT, check=True)


def preflight():
    missing = [p for p in (FORWARD_SCRIPT, RETURN_SCRIPT, TARGETED_PCR_SCRIPT) if not p.exists()]
    if missing:
        lines = "\n".join(f"  {p}" for p in missing)
        raise SystemExit(f"Refusing to run: required script(s) not found:\n{lines}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Full PTA/HHS iSWAP forward + return, then targeted PCR full dry "
            "choreography. Dry / camera choreography only."
        )
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Must equal {CONFIRM_TOKEN} to run.",
    )
    args = parser.parse_args()

    if args.confirm != CONFIRM_TOKEN:
        raise SystemExit(
            f"Refusing to run. Add: --confirm {CONFIRM_TOKEN}"
        )

    preflight()

    print("")
    print("FULL PTA/HHS iSWAP -> targeted PCR DRY CHOREOGRAPHY (return tips)")
    print("Dry / camera choreography only. Use an EMPTY sacrificial plate.")
    print("Destination nests must be physically empty. Hand near E-stop.")

    run_phase(1, "PTA/HHS iSWAP forward: rail35 pos0 -> rail27 pos2 (HHS)", FORWARD_CMD)
    run_phase(2, "PTA/HHS iSWAP return: rail27 pos2 (HHS) -> rail35 pos0", RETURN_CMD)
    run_phase(3, "targeted PCR full built dry choreography", TARGETED_PCR_CMD)

    print("")
    print("=" * 88)
    print("ALL PHASES COMPLETE.")
    print("=" * 88)


if __name__ == "__main__":
    main()
