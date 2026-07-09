#!/usr/bin/env bash
set -euo pipefail

cd ~/star-lab
source env/bin/activate

SCRIPT="00_pta_wga_col1_swap_source_staged_discardtips_P10_sourceH00_dspH05_bo7.py"

echo
echo "=== PTA/WGA REAL E2E RUNNER: DISCARD TIPS ==="
echo "REAL mode: no --return-tips. Tips will be DISCARDED."
echo "Use only with real reagents/samples and fresh tip columns."
echo

echo "Checking STAR USB..."
lsusb | grep -i 08af

echo
echo "Checking no obvious STAR protocol process is already running..."
ps aux | grep -E "00_pta_wga|pylabrobot" | grep -v grep || true

echo
read -p "Confirm deck clear + fresh p10 tips loaded. Press Enter for deck check..."

python "$SCRIPT" --mode deck

echo
echo "=== STEP 1: REAL LYSIS MIX ADDITION ==="
echo "Deck:"
echo "  rail48 pos0 = p10 tips, column 1 fresh"
echo "  rail35 pos0 = destination/work plate, column 1 A-H contains 3 uL sample/cell buffer/control"
echo "  rail35 pos1 = source plate/strip, column 1 A-H contains Lysis Mix"
echo
echo "This step will run: python \$SCRIPT --mode lysis"
echo "Tips will be DISCARDED."
echo
read -p "Type RUN_REAL_PTA to run real lysis: " CONFIRM
if [[ "$CONFIRM" != "RUN_REAL_PTA" ]]; then
  echo "Aborted before lysis."
  exit 1
fi

python "$SCRIPT" --mode lysis

echo
echo "LYSIS STAR STEP COMPLETE."
echo "Now do real protocol handoff:"
echo "  seal/spin"
echo "  thermal mixer: room temp, 20 min, 1400 rpm"
echo "  spin"
echo "  place back on ice"
echo
read -p "After real lysis incubation/handoff is complete, press Enter..."

echo
echo "=== STEP 2: REAL REACTION MIX ADDITION ==="
echo "Deck:"
echo "  rail48 pos0 = p10 tips, column 2 fresh"
echo "  rail35 pos1 = source plate/strip, column 1 A-H contains Reaction Mix"
echo "  rail35 pos0 = destination/work plate clear/no obstruction"
echo
echo "This step will run: python \$SCRIPT --mode reaction"
echo "Tips will be DISCARDED."
echo
read -p "Type RUN_REAL_REACTION to run real reaction: " CONFIRM
if [[ "$CONFIRM" != "RUN_REAL_REACTION" ]]; then
  echo "Aborted before reaction."
  exit 1
fi

python "$SCRIPT" --mode reaction

echo
echo "REACTION STAR STEP COMPLETE."
echo "Now do real protocol handoff:"
echo "  seal/spin"
echo "  thermal mixer: room temp, 1 min, 1000 rpm"
echo "  spin"
echo "  keep plate on ice"
echo
read -p "Press Enter for final PTA thermocycler handoff..."

echo
echo "=== PTA THERMOCYCLER HANDOFF ==="
echo "Load plate into thermocycler:"
echo "  30 C for 2.5 hr"
echo "  65 C for 3 min"
echo "  4 C hold"
echo
echo "PTA/WGA real E2E handoff complete."
