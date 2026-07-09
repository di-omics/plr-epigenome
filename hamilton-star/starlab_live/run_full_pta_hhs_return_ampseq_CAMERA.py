#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

PTA_FULL = ROOT / "00_pta_wga_96wp_demo_all12_DSPH15_DRY_ISWAP_R27P2_HHS.py"
HHS_RETURN = ROOT / "test_iswap_plate_rail27pos2_hhs_to_rail35pos0_return.py"
AMPSEQ_FULL = ROOT / "09_ampseq_full_built_end_to_end_dry.py"


def run_phase(name: str, cmd: list[str]) -> None:
    print("\n" + "=" * 80, flush=True)
    print(f"CAMERA PHASE: {name}", flush=True)
    print("=" * 80, flush=True)
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuous camera runner: full PTA dry -> HHS return -> full ampseq dry."
    )
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()

    if args.confirm != "RUN_FULL_PTA_HHS_RETURN_AMPSEQ_CAMERA":
        raise SystemExit(
            "Refusing to run. Use: --confirm RUN_FULL_PTA_HHS_RETURN_AMPSEQ_CAMERA"
        )

    for p in [PTA_FULL, HHS_RETURN, AMPSEQ_FULL]:
        if not p.exists():
            raise SystemExit(f"Missing required script: {p}")

    print("\nFULL CONTINUOUS CAMERA RUN", flush=True)
    print("Expected start state:", flush=True)
    print("  plate on rail35 pos0", flush=True)
    print("  rail27 pos2 HHS empty/ready", flush=True)
    print("  rail35 pos2 mag ready", flush=True)
    print("  tips/reagents/reservoirs loaded for dry choreography", flush=True)
    print("  deck clear, camera on, hand near E-stop", flush=True)

    run_phase(
        "1/3 FULL PTA DRY PIPETTING + HHS DROP",
        [
            PYTHON,
            str(PTA_FULL),
            "--mode",
            "full-demo-iswap",
            "--return-tips",
            "--tip-col",
            "1",
            "--iswap-drop-x-offset-mm",
            "12.0",
            "--iswap-drop-y-offset-mm",
            "54.5",
            "--iswap-drop-z-offset-mm",
            "17.0",
            "--confirm",
            "RUN_FULL_PTA_ISWAP_DEMO",
        ],
    )

    run_phase(
        "2/3 HHS RETURN rail27 pos2 -> rail35 pos0",
        [
            PYTHON,
            str(HHS_RETURN),
            "--hhs-pickup-x-offset-mm",
            "12.0",
            "--hhs-pickup-y-offset-mm",
            "54.5",
            "--hhs-pickup-z-offset-mm",
            "9.0",
            "--return-drop-z-offset-mm",
            "8.5",
        ],
    )

    run_phase(
        "3/3 FULL AMPSEQ DRY CHOREOGRAPHY",
        [
            PYTHON,
            str(AMPSEQ_FULL),
        ],
    )

    print("\n" + "=" * 80, flush=True)
    print("FULL CONTINUOUS CAMERA RUN COMPLETE", flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
