# tipseq-plr

Automated **(sci)TIP-seq** on a **Hamilton STAR**, written in [PyLabRobot](https://docs.pylabrobot.org).

Turns the published protocol:

> Bartlett, Dileep, Handa, Ohkawa, Kimura, Henikoff, Gilbert (2021).
> *High-throughput single-cell epigenomic profiling by targeted insertion of promoters (TIP-seq).*
> **J Cell Biol** 220(12):e202103078. https://doi.org/10.1083/jcb.202103078

into an end-to-end, deck-resident method that a robot runs unattended, from bead-bound cells through a sequence-ready, QC'd library plate.

Instruments driven:

| Role | Device | Backend |
|---|---|---|
| Liquid handling | Hamilton STAR / STARlet | `pylabrobot` `STARBackend` |
| On-deck thermocycling | Inheco **ODTC** | `backends/inheco_odtc.py` (SiLA 2) |
| Heat + mix incubations | Hamilton Heater-Shaker (or Inheco ThermoShake) | `pylabrobot` heating_shaking |
| Bead separation | passive magnet nest (Alpaqua/Ambion) | plate move + settle |
| Library QC | **Tecan Infinite 200 Pro** | `backends/tecan_pro200.py` |

## Protocols

Every runnable method lives under **[`tipseq_plr/protocols/`](tipseq_plr/protocols)**, one self-contained package per protocol. They all compose the same shared infrastructure at the package root (`config`, `deck`, `devices`, `reagents`, `backends`, `steps`), so a protocol package only holds what is specific to that method: its parameters, its orchestration, and its CLI.

| Protocol | Directory | What it does | Status | CLI |
|---|---|---|---|---|
| **(sci)TIP-seq** | [`protocols/tipseq/`](tipseq_plr/protocols/tipseq) | single-cell epigenomic library prep (Bartlett 2021); plate / bulk / sci variants, with an optional FACSMelody sort to close the sci path | untested | `python -m tipseq_plr.protocols.tipseq.run` |
| **CUT&Tag** | [`protocols/cut_and_tag/`](tipseq_plr/protocols/cut_and_tag) | chromatin profiling (Kaya-Okur 2019); TIP-seq's front half then direct indexing PCR instead of IVT | untested | `python -m tipseq_plr.protocols.cut_and_tag.run` |
| **Plate normalization** | [`protocols/normalization/`](tipseq_plr/protocols/normalization) | Qubit HS quant on the Tecan, then normalize a 96-well plate to a uniform concentration | untested | `python -m tipseq_plr.protocols.normalization.run` |
| **HyDrop scATAC** | [`protocols/hydrop_atac/`](tipseq_plr/protocols/hydrop_atac) | droplet-based scATAC (De Rop 2024); STAR wet chemistry bridged to an Onyx droplet generator by a robot arm | untested | `python -m tipseq_plr.protocols.hydrop_atac.run` |

**Status** is the validation tier (see [Validation](#validation-and-confidence)). All four read `untested`: they run in simulation but have no paired Rhodamine B evidence yet. That is the honest label until a liquid test clears the bar.

Each protocol package has the same shape: `config.py` (paper-traceable parameters), `protocol.py` (the orchestrator), `run.py` (a CLI), and any protocol-specific helpers (for example `normalization/plan.py`). A new protocol is a new folder here; it does not touch the shared root. Cross-cutting tooling that is not itself a protocol (the FACSMelody reverse-engineering harness) stays at the root under `reverse_engineering/`.

## Validation and confidence

The objective of this repo is a path from **PyLabRobot to a protocol on the Hamilton STAR to liquid-tested validation**, so a method can be trusted, not just simulated. Every protocol carries a validation tier that it only earns with data:

| Tier | Meaning | Evidence |
|---|---|---|
| **untested** | PLR-authored, dry-runs in simulation. No physical evidence the STAR dispenses what the code says. | none (the starting point) |
| **liquid_tested** | Liquid-handling accuracy and precision verified on the STAR. A claim about **volumes**, not biology. | a **Rhodamine B** assay with paired plate-reader data that clears the success criteria |
| **biovalidated** | The protocol produces the expected biological result. | tracked **privately, not in this public repo** |

A protocol is `liquid_tested` **only when** a Rhodamine B dispense series, read on the plate reader with paired data, passes all of: paired replicates present, every reading inside the reader's linear range, standard-curve R² ≥ 0.995, and per-volume accuracy and CV within tolerance (tolerances loosen below 10 uL and below 2 uL). No partial credit: if any check fails, it stays `untested` with the reasons listed. **Biovalidation is deliberately out of this public repo.** Full criteria and the evaluator: [docs/validation.md](docs/validation.md).

```bash
python -m tipseq_plr.validation.cli status                       # the confidence ladder
python -m tipseq_plr.validation.cli evaluate --data run.json     # gate a Rhodamine B dataset
```

The evaluator ([`validation/rhodamine.py`](tipseq_plr/validation/rhodamine.py)) is a pure function and exits non-zero unless the bar is cleared, so it can gate CI or a release.

## Run it now (no hardware)

Everything runs in **simulation** with zero hardware and zero external drivers, PyLabRobot doesn't even need to be installed (it falls back to a logging "dry" mode). With PyLabRobot installed, simulation routes through its chatterbox backend so you see every atomic aspirate/dispense.

```bash
# dry-run the fully-autonomous plate TIP-seq for 96 samples
python -m tipseq_plr.protocols.tipseq.run --method plate_tipseq --samples 96 --simulate -v

# sciTIP-seq: prints the FACS handoff boundary, then continues
python -m tipseq_plr.protocols.tipseq.run --method scitip_seq --samples 96 --simulate

# just the reagent prep sheet + labware checklist
python -m tipseq_plr.protocols.tipseq.run --plan-only

# feel the wall-clock (17 h IVT compressed): 1e-5 of real time
python -m tipseq_plr.protocols.tipseq.run --method plate_tipseq --sim-time-scale 0.00001
```

Output ends with a QC verdict per well (`pass` / `dilute` / `fail`) from the simulated Tecan read. `--report out.json` writes the full report.

## What maps to what

The protocol is six deck-resident stages (`tipseq_plr/steps/`):

| Stage | Module | Paper section |
|---|---|---|
| 0 preload | (none) | cells harvested/permeabilized, aliquoted per well (off-deck) |
| 1 targeting | `binding.py` | conA capture -> primary Ab -> secondary Ab -> pA-Tn5 (T7 transposon) |
| 2 tagmentation | `tagmentation.py` | 37 °C tagment -> EDTA stop -> SDS/proteinase K -> SPRI |
| 3 linear amp | `ivt.py` | gap-fill (72 °C) -> T7 IVT (37 °C, ~17 h) -> RNA SPRI |
| 4 cDNA | `cdna.py` | random-hexamer RT -> RNase H -> second-strand -> SPRI |
| 5 library | `library.py` | ME-B Tn5 fragmentation -> PCR indexing -> 0.85× size-select |
| 6 QC | `qc.py` | Tecan dsDNA fluorescence quant + pass/dilute/fail gate |

Every volume, temperature, and incubation time lives in `config.py`, each traceable to the paper's Materials & Methods. Change the run there, not in the step code.

## The one honest caveat: FACS

`sciTIP-seq` combinatorial indexing requires a **FACS re-distribution of pooled cells between index 1 and index 2**, that's why the published sci method omits conA beads. **A STAR cannot sort cells.** So:

- **`plate_tipseq` / `bulk_tipseq`** keep cells on conA beads the whole way -> every separation is a magnet step -> **fully autonomous, one shot.** This is the recommended production path for up to 96 barcoded samples/targets in parallel.
- **`scitip_seq`** runs index-1 tagmentation on deck, then hits the FACS boundary. Three ways it resolves:
  - **Manual (default):** on hardware it raises `FacsHandoffRequired`; an operator sorts the pool into the index-2 plate and calls `proto.resume_after_facs()`.
  - **Automated (`sorter_enabled=True`):** the boundary drives a **BD FACSMelody** sort-to-plate via a reverse-engineered `ProtocolMap`, closed-loop, no human.
  - **Simulation:** prints the boundary and continues so you can validate the whole flow.

This is a property of the assay, not the code. If you want a single-tube high-plex path with no sort, that's a protocol redesign (e.g. droplet or split-pool without live-cell sorting), flagged, not hidden.

### Closing the FACS gap: the reverse-engineering toolkit

`tipseq_plr/reverse_engineering/` is a staged harness that applies **Rick Wierenga's PyLabRobot methodology** (work to the OEM command layer -> sniff OEM↔device traffic -> correlate each UI action to its bytes -> decode framing -> replay via PyUSB/serial) to the BD FACSMelody + FACSChorus. Its output is a `ProtocolMap` the `BDFACSMelodyBackend` loads. Replay is guarded by two independent safety switches (`--armed`, `--live`) plus an `--allow-actuation` gate for anything that moves fluid or fires a sort, and the backend **refuses to run a live sort until every required command is decoded.** Full playbook: [docs/facs-melody-re.md](docs/facs-melody-re.md).

```bash
python -m tipseq_plr.reverse_engineering.cli discover --tcp-host <ip>   # find the link
python -m tipseq_plr.reverse_engineering.cli chorus                     # mine Chorus logs/DB
python -m tipseq_plr.reverse_engineering.cli mark --out marks.json      # label actions while sniffing
python -m tipseq_plr.reverse_engineering.cli decode --capture cap.pcapng --marks marks.json --out protocol.json
python -m tipseq_plr.reverse_engineering.cli coverage --protocol protocol.json
```

## CUT&Tag

Chromatin profiling by CUT&Tag (Kaya-Okur et al. 2019). CUT&Tag is TIP-seq's front half: it shares the exact same conA capture, primary and secondary antibody, pA-Tn5 binding, and tagmentation stages. The only difference is the tail: the pA-Tn5 carries standard Nextera ME-A/B adapters (not the ME-T7 transposon), so the tagmented, purified gDNA goes straight into indexing PCR instead of IVT and cDNA synthesis.

```bash
python -m tipseq_plr.protocols.cut_and_tag.run --samples 96 --simulate -v
```

Because it reuses the shared [`steps/binding.py`](tipseq_plr/steps/binding.py) and [`steps/tagmentation.py`](tipseq_plr/steps/tagmentation.py) stages, the CUT&Tag orchestrator is short: front half, 2.0x SPRI purify, indexing PCR (12 to 15 cycles, 14 default), 1.1x cleanup, Tecan QC. Cells stay on conA beads throughout, so like plate/bulk TIP-seq it runs fully autonomously with no sort. This is also the clearest illustration of the shared-infrastructure design: a second published method drops in as a thin orchestrator over the same stages.

## Plate normalization (Qubit HS)

A standalone, shippable protocol: quantify a 96-well source plate and normalize it to a uniform concentration. Independent of the TIP-seq flow, it reuses the same STAR deck and Tecan backend.

Flow: **12 uL source plate -> high-sensitivity Qubit dsDNA prep (2 uL aliquot into a black assay plate) -> Tecan read (Ex485/Em530) + standard curve -> per-well concentration -> normalize sample + water into a destination plate** at a target concentration and volume.

```bash
# normalize 96 wells to 1 ng/uL in 20 uL, from a 12 uL source plate
python -m tipseq_plr.protocols.normalization.run --samples 96 --target 1.0 --final 20 --simulate -v
python -m tipseq_plr.protocols.normalization.run --report norm.json     # full per-well plan as JSON
```

The normalization math ([`protocols/normalization/plan.py`](tipseq_plr/protocols/normalization/plan.py)) is a pure, unit-tested function. Each well is classified: `ok` (hits target exactly), `capped_low` (too dilute to reach target in the final volume, transfers max available and flags it), `needs_predilution` (so concentrated the ideal transfer is below the smallest reliable volume), or `empty`. Volume is always conserved (`sample + water == final`). Nothing is silently mis-normalized: out-of-range wells are reported, not hidden.

```python
from tipseq_plr.protocols.normalization import NormConfig, PlateNormalization
import asyncio
cfg = NormConfig(num_samples=96, source_volume_ul=12.0,
                 target_ng_per_ul=1.0, final_volume_ul=20.0, simulate=True)
report = asyncio.run(PlateNormalization(cfg).run())   # -> counts + per-well plan
```

## HyDrop scATAC with an Onyx droplet-generation bridge

Automates HyDrop single-cell ATAC library prep by pairing the STAR (wet chemistry) with a Droplet Genomics / Atrandi **Onyx** (droplet generation), connected by a **PLR-driven robot arm** that carries labware between them. The arm is a reusable inter-instrument bridge, so the same abstraction also handles the FACSMelody plate handoff.

Protocol basis: the HyDrop ATAC methods in [De Rop et al., Nat Biotechnol 42:916-926 (2024)](https://doi.org/10.1038/s41587-023-01881-x). The STAR does nuclei prep, tagmentation, and co-encapsulation assembly; the arm carries the loaded chip to the Onyx; the Onyx generates the emulsion; the arm carries it to the ODTC for linear amplification; the STAR finishes with emulsion break, Dynabead/Ampure cleanup, index PCR, size selection, and Tecan QC.

```bash
python -m tipseq_plr.protocols.hydrop_atac.run --samples 8 --simulate -v
```

The log shows the handoffs: `arm: pick onyx_chip from star_transfer -> place at onyx_load`, `Onyx: generate droplets -> collected 100 uL`, `arm: ... emulsion_plate onyx_output -> odtc_nest`. Two new backends make it work: [`RobotArmBackend`](tipseq_plr/backends/robot_arm.py) (generic arm over taught transfer sites, live motion gated behind `enabled=True` and a speed cap) and [`OnyxBackend`](tipseq_plr/backends/droplet_genomics_onyx.py) (pressure-driven droplet generation, actuation gated behind `armed=True`). Full playbook: [docs/hydrop-onyx-bridge.md](docs/hydrop-onyx-bridge.md).

## Going live

`--simulate` is the default and everything above is real PyLabRobot API surface. To run on hardware:

1. `pip install "pylabrobot>=0.1.6"` and confirm the STAR/ODTC/HHS/reader versions you have.
2. In `deck.py`, pin the exact labware in `pin_labware()` to your inventory (tips, plates, reservoirs, magnet, black QC plate). The `_make_*` helpers fall back to generic geometry so the module always imports; a physical run should use your validated definitions.
3. Wire the two shim backends to your instruments:
   - `backends/inheco_odtc.py` -> map the friendly commands (`SetBlockTemperature`, `HoldTemperature`, lid actuation) to the ODTC's SiLA 2 feature set. PyLabRobot's first-party ODTC backend (forum PRs #841/#1026) can drop in here when released.
   - `backends/tecan_pro200.py` -> connect i-control/Magellan (SiLA or COM automation), or shell out to a headless exported method.
   - `devices.py::HeaterShakerDevice.setup` -> instantiate `HamiltonHeaterShakerBackend` or `InhecoThermoShakeBackend`.
4. Run with `--no-simulate` and your device addresses (`--` flags map to `RunConfig`: `odtc_host/port`, `hhs_com`, `tecan_host`).

Nothing about the biochemistry sequencing changes between sim and hardware, only the backend transport.

## Architecture

```
tipseq_plr/
  # --- shared infrastructure (every protocol composes these) ---
  config.py          TIP-seq parameters (volumes/temps/times), paper-traceable, no PLR import
  deck.py            STAR deck layout; labware pinning; version-tolerant fallbacks
  reagents.py        reagent -> reservoir map; prep-sheet planner; dead-volume guard
  devices.py         uniform async wrappers over STAR / HHS / ODTC / reader / magnet / arm / onyx / vspin
  steps/             TIP-seq stage library + shared helpers (LiquidOps, qc math)
    common.py        LiquidOps: column-wise pipetting, SPRI cleanup, magnet washes
    thermal.py       heater-shaker holds + ODTC ramp programs
    binding.py ... qc.py   the six TIP-seq stages
  backends/
    inheco_odtc.py   SiLA-ready ODTC thermocycler backend (+ simulation)
    tecan_pro200.py  Tecan Infinite 200 Pro reader backend (+ simulation)
    bd_facsmelody.py BD FACSMelody sorter backend; loads a decoded ProtocolMap
    robot_arm.py     generic PLR-driven inter-instrument arm (taught sites, gated)
    droplet_genomics_onyx.py  Onyx droplet-generation backend (+ simulation)
    vspin.py         VSpin centrifuge backend; deck-integrated, balance-guarded
  reverse_engineering/   FACSMelody RE toolkit (Rick Wierenga methodology; not a protocol)
    model.py / transport_discovery.py / chorus_probe.py / capture.py
    correlate.py / decode.py / replay.py / cli.py
  validation/            liquid-test confidence framework (not a protocol)
    status.py            ValidationTier ladder + per-protocol public status
    rhodamine.py         Rhodamine B success criteria (accuracy / CV / range / R2)
    cli.py               status | evaluate (gates the liquid_tested claim)

  # --- protocols: one self-contained package per runnable method ---
  protocols/
    tipseq/          (sci)TIP-seq orchestrator + CLI (incl. FACS handoff / sorter)
      protocol.py    TipSeqProtocol
      run.py         CLI
    cut_and_tag/     CUT&Tag: shared front half + direct indexing PCR
      config.py      CutAndTagConfig (PCR tail; reuses TIP-seq buffers)
      protocol.py    CutAndTag orchestrator
      run.py         CLI
    normalization/   Qubit HS quant + 96-well normalization
      config.py      NormConfig / QubitHS assay parameters
      plan.py        pure normalization math (per-well sample/water plan)
      protocol.py    PlateNormalization
      run.py         CLI
    hydrop_atac/     HyDrop scATAC with an Onyx droplet-gen step (arm-bridged)
      config.py      HyDrop buffers / volumes / thermal programs (paper-traceable)
      protocol.py    HyDropATAC: STAR -> arm -> Onyx -> arm -> STAR
      run.py         CLI
docs/facs-melody-re.md      FACSMelody reverse-engineering playbook
docs/hydrop-onyx-bridge.md  HyDrop + Onyx + robot-arm playbook
tests/               dry-mode smoke + logic tests (all protocols + toolkits)
```

Design rules: protocol code never imports a vendor backend or branches on sim/real, it only calls `devices.py` wrappers and the shared `steps`. Swapping an instrument is a one-line change in `build_devices`; adding a protocol is a new folder under `protocols/` that leaves the shared root untouched.

## Status

- ✅ End-to-end simulation of all three methods, 8-96 samples (incl. sci with a simulated FACSMelody sort).
- ✅ Reagent prep sheet + labware checklist generation.
- ✅ dsDNA QC with standard-curve fit and pass/dilute/fail gating.
- ✅ FACSMelody RE toolkit: transport discovery, capture ingest, action->byte correlation, framing/checksum decode, guarded replay, all runnable offline.
- 🔌 ODTC, Tecan, and FACSMelody backends are interface-complete shims; the Melody `ProtocolMap` is produced by running the RE playbook against your instrument.
- 🧪 Not yet wet-lab validated. Treat as a method to dry-run, review, and adapt, not a validated SOP.

## License

MIT.
