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
    print("")
    print("PCR ENRICHMENT ROUND 2 COLUMN-1 TWO-PART DISCARD-TIP OBSERVER")
    print("")
    print("DRY OBSERVATION RUN:")
    print("  This performs the same PCR2 movements as the real run.")
    print("  Tips are discarded, not returned.")
    print("")
    print("Deck assumptions:")
    print("  rail35 pos1 col3 A-H = PCR2 MM + i5/i7 primers or dry/mock source")
    print("  rail35 pos1 col1 A-H = operator-staged PCR enrichment round 1 samples or dry/mock source")
    print("  rail35 pos0 col1 A-H = destination PCR2 wells")
    print("  rail48 pos1 = p50 tips")
    print("  rail48 pos0 = p10 tips")
    print("")
    print("Order:")
    print("  1. p50: add operator-prepared round 2 reagent from source col3 to destination col1")
    print("  2. p10: add operator-prepared sample from source col1 to destination col1")
    print("  3. discard both tip sets")
    print("")

    run_step(
        "STEP 1: round 2 reagent, operator volume, source col3 -> destination col1, p50, DISCARD TIPS",
        [
            sys.executable,
            str(PCR2_MM_SCRIPT),
            "--mode",
            "pcr2-mm",
            "--tip-col",
            "2",
        ],
    )

    run_step(
        "STEP 2: operator-prepared sample, operator volume, source col1 -> destination col1, p10, DISCARD TIPS",
        [
            sys.executable,
            str(PCR2_SAMPLE_SCRIPT),
            "--mode",
            "pcr1-mm",
            "--tip-col",
            "1",
        ],
    )

    print("")
    print("SUCCESS: PCR2 discard-tip observer completed.")
    print("For the real wet run, use fresh p50 and p10 tip columns.")
    print("")


if __name__ == "__main__":
    main()
