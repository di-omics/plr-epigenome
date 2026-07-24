# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Control scripts for a physical **Hamilton STAR** liquid handler, driven by **PyLabRobot** (`pylabrobot` 0.2.1) over USB from a Raspberry Pi (`starpi`). There is no application or test suite – each `.py` file is a standalone `asyncio` script that homes the robot, assigns a deck, and executes one liquid-handling protocol or hardware test. Running a script with the real backend **moves real hardware**.

## Hardware safety (read this first)

Real `STARBackend` runs are **human-gated**. These rules are not optional:

- **Never run hardware unattended.** A person must be watching the deck for every real run.
- **Always dry-run first** on `STARChatterboxBackend(skip_autoload=True)`, which simulates the protocol and prints commands without moving anything. Only after a clean chatterbox run should a human-gated `STARBackend` run follow.
- **Always run `--mode deck` first on hardware** (assignment only, no movement) to confirm the deck layout matches reality before any liquid-handling mode.
- **Single-cell WGS preparation discards tips, never returns them** (carryover contamination is fatal to single-cell work). Returning tips (`--return-tips`) is acceptable only for water/dry rehearsals, never for real reagent runs.
- **Verify PyLabRobot API claims against the installed source** in `env/`. AI summaries frequently misreport PLR import paths and signatures; trust the 0.2.1 source, not recollection.

### Known PLR 0.2.1 quirk (not a bug)

Aspirating from a trough with a broadcast well list (`trough["A1"] * 8`) trips PLR's `_position_channels_wide` check **in the chatterbox backend only**. It passes on real hardware because the firmware handles the geometry. Expect this dry-run failure for trough steps; it is not a defect to fix.

## Running scripts

```bash
source env/bin/activate          # venv lives on the Pi only; gitignored, not in source
python <script>.py               # most scripts; runs asyncio.run(main())
python 00_wgs_prep_...py --mode deck   # production scripts: assign deck only, NO movement (safe pre-check)
```

- `env/` is the Python 3.13 virtualenv. It is gitignored and exists only on `starpi`; do not commit it or assume it exists when working off-robot.
- The STAR connects via USB, Hamilton vendor id `08af` (`lsusb | grep -i 08af`). If it's missing the robot is off or unplugged.
- `run_wgs_prep_dry_e2e.sh` is a guided, interactive **dry rehearsal** of the whole-genome sequencing workflow – it prompts the operator between steps and runs the protocol script with `--return-tips`.
- Assay scripts require `PLR_METHOD_PARAMETERS_FILE` to point to an
  operator-approved local JSON profile. Public code contains no wet-lab recipe
  defaults; see `../METHOD_PARAMETERS.md`.
- Workflow is terminal-first with the `git` CLI.

### Standard robot lifecycle (every script follows this)

```python
lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())  # swap in STARChatterboxBackend() to dry-run
await lh.setup(skip_autoload=True)   # skip_autoload=True is intentional and near-universal here
try:
    ... # assign carriers to rails, then pick_up_tips / aspirate / dispense / discard_tips
finally:
    await lh.backend.park_iswap()    # production scripts park the iSWAP before stopping
    await lh.stop()
```

## Deck layout

Carriers are assigned to **rails** (`lh.deck.assign_child_resource(carrier, rails=N)`); labware sits in **positions** within a carrier.

### Current deck (rails 35 / 48)

- `rail48`: tip carrier – p10, p50, and p300 tips
- `rail35`: plate carrier
  - `pos0` = destination/work 96WP
  - `pos1` = chilled source 96WP/strip (single-column swap-source workflow; reagent is swapped here between steps)
  - `pos2` = magnet (mag plate)
  - `pos3` = trough

### Old deck (rails 19 / 26 / 33 / 40, p1000 + p50) – superseded

The earlier-generation deck used rails 19/26/33/40 with p1000 and p50. Those scripts **still run** but target last-gen hardware geometry. Treat them as historical; new work targets the current 35/48 deck.

## Production whole-genome sequencing front-end

`00_wgs_prep_col1_swap_source_staged_discardtips_P10_sourceH00_dspH05_bo7.py` is the **current-deck whole-genome sequencing front-end**. Verified on real hardware **2026-06-15**.

- **Modes:** `lysis` and `reaction` are independently selectable, verified
  motion steps. Their liquid volumes come from the local method profile.
- **`--mode all-dev` has a `KeyError` bug – do not use it.** Run `lysis` / `reaction` individually.
- **Locked geometry:** source aspirate height `0.0`, work dispense height `0.5`, dispense XY `Coordinate(-0.68, 3.22, 0.0)`, blowout `7 µL`, `1 s` post-dispense settle.
- **Discard tips by default**; `--return-tips` only for observation/water runs (see safety rules).
- One run = one reagent addition into column 1, then stop. The operator manually **swaps the source reagent in `rail35 pos1 column 1`** between steps (8-strip caps physically block adjacent columns), so the workflow is deliberately stepwise across process restarts.

### Production CLI conventions (the `00_`/`03_` whole-genome sequencing & library-prep family)

- **`--mode`** selects a single biology step (e.g. `deck`, `lysis`, `reaction`). `--mode deck` only assigns the deck and prints geometry – no motion. Steps are defined in a `STEPS` dict of `Step` dataclasses carrying volume, tip type, and operator prep/stop instructions.
- **`--return-tips`** returns tips to the rack instead of discarding. **Default is discard** (production).
- **`--tip-col N`** overrides the tip rack column; otherwise `DEFAULT_TIP_COL_BY_MODE` advances columns so separate runs never reuse a tip position.
- Tip-rack factory names vary by PyLabRobot build; production scripts probe a candidate list via `getattr(plr_resources, ...)` (see `make_resource`) rather than hardcoding one name.

### Geometry is empirically tuned – treat the header comments as the changelog

Aspirate/dispense **heights** and XY **`Coordinate` offsets** are tuned by hand against the physical deck and locked as module constants (e.g. `P10_SOURCE_ASP_HEIGHT`, `P10_WORK_DSP_OFFSETS`, `*_BLOWOUT_AIR_VOLUME`). The long block of dated `PATCH` comments at the top of each production script is the **authoritative record of why each value is what it is**, including known-bad values. Before changing any coordinate or height, read that block – it records hard constraints discovered the hard way.

## Known-bad / blacklisted values

- **Dispense `Y = 3.20` causes a `<9 mm adjacent-channel spacing` safety error** and is blacklisted across all production scripts. `BAD_y320_do_not_run.py` captures this dead-end; tune Y in tiny steps and never drop to 3.20.
- `liquid_height` cannot go below a well's minimum legal bottom (negative source heights were rejected by the backend).

## File-naming conventions

There are many near-identical files because each tuning session is saved as a new variant. Read names before assuming intent:

- **Numbered prefixes** (`00_`, `02_`, `03_`, `04_`) = staged steps of a workflow (whole-genome sequencing, library prep, cleanup).
- **Suffixes encode tuned parameters**: `y322`/`x068` (XY), `sourceH00`/`dspH05` (heights), `bo7` (blowout µL), `P10`/`P50` (pipette), `tipcolN`, `returntips`/`discardtips`.
- `_PROD` / `PRODUCTION` = the validated production variant. `_FINAL`, `_WORKING`, `_SAFE` = operator-confirmed-good checkpoints.
- `BAD_*` / `*_do_not_run.py` = known-dangerous, do not execute.
- `recover_*` = manual recovery actions after a crash/restart (drop held plate, release iSWAP, drop tips).
- `test_*`, `*_test`, `*_demo`, `*_qc` = single-feature hardware checks (iSWAP moves, single transfers, tip pickup).
- `home_*` / `init_*` = bring-up scripts that home channels and the iSWAP.

When asked to "tune" or "make a safe variant," follow this pattern: copy the closest-good script to a new descriptive filename, change only the named constants, and prepend a dated comment block explaining the change and what was rejected – do not edit a `_PROD` file in place.

## Formatting

Use en-dashes (–), never em-dashes (—), in code comments, docs, and committed text.
