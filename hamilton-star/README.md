# Hamilton STAR / PyLabRobot

Protocols and validation scripts for the research lab Hamilton Microlab STAR controlled by PyLabRobot on `starpi`.

Assay volumes, incubation durations, ratios, thermal programs, and QC gates
come from an operator-approved local profile and are not stored in the public
repository. See [`METHOD_PARAMETERS.md`](METHOD_PARAMETERS.md). Hardware
geometry and safety calibration remain in the scripts.

## Repository layout

- `setup/` - STARPI setup, SSH, USB, and safe startup notes.
- `protocols/whole_genome_seq/` - earlier WGS preparation protocol scripts.
- `protocols/validation/wgs_prep/` - current validation WGS preparation runners.
- `protocols/validation/pcr_enrichment/` - current PCR enrichment validation scripts.
- `tests/liquid_handling/` - generic STAR liquid-handling validation scripts.
- `tests/whole_genome_seq/` - WGS-preparation focused tests.
- `tests/movement/` - movement, lid, and iSWAP tests.
- `archive/` - preserved debugging checkpoints.

## Current active deck: validation / rail35-48 layout

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

- `protocols/validation/wgs_prep/run_wgs_prep_dry_e2e.sh`
  - Dry observation only.
  - Uses `--return-tips`.
  - Deck check -> lysis add -> manual lysis handoff -> reaction add -> thermocycler handoff.

- `protocols/validation/wgs_prep/run_wgs_prep_REAL_DISCARD_TIPS_e2e.sh`
  - Real whole-genome sequencing runtime template.
  - Does not use `--return-tips`.
  - Requires typed confirmations before real lysis and reaction additions.

## Current PCR enrichment entrypoints

- `protocols/validation/pcr_enrichment/01_pcr_enrichment_round1_mastermix_col1.py`
  - Validated dry.
  - p50 transfer volume comes from the operator-approved local profile.
  - Source rail35 pos1 col1 -> destination rail35 pos0 col1.

- `protocols/validation/pcr_enrichment/03_pcr_enrichment_round2_mastermix_col1.py`
  - Validated dry.
  - p50 transfer volume comes from the operator-approved local profile.
  - Source rail35 pos1 col1 -> destination rail35 pos0 col1.

- `protocols/validation/pcr_enrichment/02_pcr_enrichment_round1_cleanup_col1_dry_v2_p50low.py`
  - Validated first dry p50-low cleanup motion.
  - Intended next work: mock-liquid bead clean validation.

## Current priorities

1. Hamilton bead clean for PCR enrichment.
2. Sample validation: WGS preparation, Viaflow/manual vs Hamilton.
3. Sample validation: PCR enrichment, Viaflow/manual vs Hamilton.
