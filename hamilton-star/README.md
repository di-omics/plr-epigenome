# Hamilton STAR / PyLabRobot

Protocols and validation scripts for the Preventive Medicine Hamilton Microlab STAR controlled by PyLabRobot on `starpi`.

## Repository layout

- `setup/` - STARPI setup, SSH, USB, and safe startup notes.
- `protocols/whole_genome_seq/` - earlier WGS preparation protocol scripts.
- `protocols/bio_validation0/pta_wga/` - current Bio Validation 0 PTA/WGA runners.
- `protocols/bio_validation0/targeted_pcr/` - current Bio Validation 0 targeted PCR library preparation scripts.
- `tests/liquid_handling/` - generic STAR liquid-handling validation scripts.
- `tests/whole_genome_seq/` - WGS-preparation focused tests.
- `tests/movement/` - movement, lid, and iSWAP tests.
- `archive/` - preserved debugging checkpoints.

## Current active deck: Bio Validation 0 / rail35-48 layout

```text
rail48 pos0 = p10 tips
rail48 pos1 = p50 tips
rail35 pos0 = destination/work plate or strip
rail35 pos1 = source/reagent plate or strip
```

Cleanup development may additionally use:

```text
rail35 pos2 = cleanup/magnet plate
rail35 pos3 = trough/reservoir
```

## Current whole-genome sequencing entrypoints

- `protocols/bio_validation0/pta_wga/run_pta_wga_dry_e2e.sh`
  - Dry observation only.
  - Uses `--return-tips`.
  - Deck check -> lysis add -> manual lysis handoff -> reaction add -> thermocycler handoff.

- `protocols/bio_validation0/pta_wga/run_pta_wga_REAL_DISCARD_TIPS_e2e.sh`
  - Real whole-genome sequencing runtime template.
  - Does not use `--return-tips`.
  - Requires typed confirmations before real lysis and reaction additions.

## Current targeted PCR library preparation entrypoints

- `protocols/bio_validation0/targeted_pcr/01_targeted_pcr_round1_mastermix_col1.py`
  - Validated dry.
  - p50 transfer: 22.5 uL x8 complete PCR1 master mix.
  - Source rail35 pos1 col1 -> destination rail35 pos0 col1.

- `protocols/bio_validation0/targeted_pcr/03_targeted_pcr_round2_mastermix_col1.py`
  - Validated dry.
  - p50 transfer: 20.5 uL x8 common PCR2 master mix.
  - Source rail35 pos1 col1 -> destination rail35 pos0 col1.

- `protocols/bio_validation0/targeted_pcr/02_targeted_pcr_round1_cleanup_col1_dry_v2_p50low.py`
  - Validated first dry p50-low cleanup motion.
  - Intended next work: mock-liquid bead clean validation.

## Current priorities

1. Hamilton bead clean for targeted PCR library preparation.
2. Embryo sample biovalidation: PTA, Viaflow/manual vs Hamilton.
3. Embryo sample biovalidation: targeted PCR library preparation, Viaflow/manual vs Hamilton.
