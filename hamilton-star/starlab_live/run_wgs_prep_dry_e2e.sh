#!/usr/bin/env bash
set -euo pipefail

cd ~/star-lab
source env/bin/activate
: "${PLR_METHOD_PARAMETERS_FILE:?Set this to an operator-approved local method profile}"

SCRIPT="00_wgs_prep_col1_swap_source_staged_discardtips_P10_sourceH00_dspH05_bo7.py"

echo
echo "=== WGS preparation DRY E2E RUNNER ==="
echo "Dry mode: all liquid-handling steps use --return-tips."
echo

echo "Checking STAR USB..."
lsusb | grep -i 08af

echo
echo "Checking no obvious protocol process is already running..."
ps aux | grep -E "00_wgs_prep|pylabrobot" | grep -v grep || true

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
echo "  follow the operator-approved local WGS method"
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
echo "  follow the operator-approved local WGS method"
echo
read -p "Press Enter for final thermocycler handoff..."

echo
echo "=== WGS preparation THERMOCYCLER HANDOFF ==="
echo "Dry-rehearse the approved local thermocycler program."
echo
echo "WGS preparation dry E2E complete."
