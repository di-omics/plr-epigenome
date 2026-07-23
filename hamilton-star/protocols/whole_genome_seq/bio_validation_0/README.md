# WGS preparation Bio Validation 0

Purpose: first live/biological validation folder for the Hamilton STAR WGS preparation V2 rail35 workflow.

This folder contains isolated column-1 scripts. Each script performs one biological liquid-handling step, then stops so the plate can be manually sealed, spun, vortexed, thermocycled, or otherwise handled off-deck as needed.

## Current deck logic

- rail48 pos0 = p10 tips
- rail35 pos0 = destination/work 96WP
- rail35 pos1 = chilled source 96WP
- source and destination use the same 96WP plate definition
- source pos1 uses the same XY offsets as destination pos0

## 01 DNAPREP smoke test

Script: 01_dnaprep_3ul_col1_pos1source_returntips.py

Scope:
- Source: rail35 pos1, 96WP, column 1
- Destination: rail35 pos0, 96WP, column 1
- Transfer: 3.0 uL DNA Prep Master Mix into A1:H1
- Tip: p10
- Tip behavior: return tips
- Blowout: 5.0 uL
- Height: 3.3
- Offset: Coordinate(-0.65, 3.35, 0.0)

This is column 1 only and is not the full protocol.

Run:
python 01_dnaprep_3ul_col1_pos1source_returntips.py --mode deck
python 01_dnaprep_3ul_col1_pos1source_returntips.py

After the run, stop the robot workflow and manually seal/spin/vortex/spin and thermocycle as needed.
