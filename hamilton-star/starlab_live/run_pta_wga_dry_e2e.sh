#!/usr/bin/env bash
set -euo pipefail

cd ~/star-lab
source env/bin/activate

SCRIPT="00_pta_wga_col1_swap_source_staged_discardtips_P10_sourceH00_dspH05_bo7.py"

echo
echo "=== PTA/WGA DRY E2E RUNNER ==="
echo "Dry mode: all liquid-handling steps use --return-tips."
echo

echo "Checking STAR USB..."
lsusb | grep -i 08af

echo
echo "Checking no obvious protocol process is already running..."
ps aux | grep -E "00_pta_wga|pylabrobot" | grep -v grep || true

echo
read -p "Confirm deck is clear + p10 tips loaded. Press Enter for deck check..."

python "$SCRIPT" --mode deck

echo
echo "=== STEP 1: LYSIS MIX ADDITION ==="
echo "Setup:"
echo "  rail48 pos0 = p10 tips, column 1 available"
echo "  rail35 pos0 = destination/work plate, column 1"
echo "  rail35 pos1 = source plate/strip, column 1 = mock Lysis Mix"
echo
read -p "Press Enter to run LYSIS --return-tips..."

python "$SCRIPT" --mode lysis --return-tips

echo
echo "LYSIS STAR STEP COMPLETE."
echo "Now dry-rehearse protocol handoff:"
echo "  seal/spin"
echo "  thermal mixer: room temp, 20 min, 1400 rpm"
echo "  spin"
echo "  back on ice"
echo
read -p "After mock lysis incubation/handoff is complete, press Enter..."

echo
echo "=== STEP 2: REACTION MIX ADDITION ==="
echo "Setup:"
echo "  rail48 pos0 = p10 tips, column 2 available"
echo "  rail35 pos1 = source plate/strip, column 1 = mock Reaction Mix"
echo "  rail35 pos0 = destination/work plate clear/no obstruction"
echo
read -p "Press Enter to run REACTION --return-tips..."

python "$SCRIPT" --mode reaction --return-tips

echo
echo "REACTION STAR STEP COMPLETE."
echo "Now dry-rehearse protocol handoff:"
echo "  seal/spin"
echo "  thermal mixer: room temp, 1 min, 1000 rpm"
echo "  spin"
echo "  keep plate on ice"
echo
read -p "Press Enter for final thermocycler handoff..."

echo
echo "=== PTA THERMOCYCLER HANDOFF ==="
echo "Dry-rehearse loading plate into thermocycler:"
echo "  30 C for 2.5 hr"
echo "  65 C for 3 min"
echo "  4 C hold"
echo
echo "PTA/WGA dry E2E complete."
