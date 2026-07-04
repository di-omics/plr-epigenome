# tipseq-plr

Automated **(sci)TIP-seq** on a **Hamilton STAR**, written in [PyLabRobot](https://docs.pylabrobot.org).

Turns the published protocol -

> Bartlett, Dileep, Handa, Ohkawa, Kimura, Henikoff, Gilbert (2021).
> *High-throughput single-cell epigenomic profiling by targeted insertion of promoters (TIP-seq).*
> **J Cell Biol** 220(12):e202103078. https://doi.org/10.1083/jcb.202103078

- into an end-to-end, deck-resident method that a robot runs unattended, from bead-bound cells through a sequence-ready, QC'd library plate.

Instruments driven:

| Role | Device | Backend |
|---|---|---|
| Liquid handling | Hamilton STAR / STARlet | `pylabrobot` `STARBackend` |
| On-deck thermocycling | Inheco **ODTC** | `backends/inheco_odtc.py` (SiLA 2) |
| Heat + mix incubations | Hamilton Heater-Shaker (or Inheco ThermoShake) | `pylabrobot` heating_shaking |
| Bead separation | passive magnet nest (Alpaqua/Ambion) | plate move + settle |
| Library QC | **Tecan Infinite 200 Pro** | `backends/tecan_pro200.py` |

## Run it now (no hardware)

Everything runs in **simulation** with zero hardware and zero external drivers - PyLabRobot doesn't even need to be installed (it falls back to a logging "dry" mode). With PyLabRobot installed, simulation routes through its chatterbox backend so you see every atomic aspirate/dispense.

```bash
# dry-run the fully-autonomous plate TIP-seq for 96 samples
python -m tipseq_plr.run --method plate_tipseq --samples 96 --simulate -v

# sciTIP-seq: prints the FACS handoff boundary, then continues
python -m tipseq_plr.run --method scitip_seq --samples 96 --simulate

# just the reagent prep sheet + labware checklist
python -m tipseq_plr.run --plan-only

# feel the wall-clock (17 h IVT compressed): 1e-5 of real time
python -m tipseq_plr.run --method plate_tipseq --sim-time-scale 0.00001
```

Output ends with a QC verdict per well (`pass` / `dilute` / `fail`) from the simulated Tecan read. `--report out.json` writes the full report.

## What maps to what

The protocol is six deck-resident stages (`tipseq_plr/steps/`):

| Stage | Module | Paper section |
|---|---|---|
| 0 preload | - | cells harvested/permeabilized, aliquoted per well (off-deck) |
| 1 targeting | `binding.py` | conA capture -> primary Ab -> secondary Ab -> pA-Tn5 (T7 transposon) |
| 2 tagmentation | `tagmentation.py` | 37 °C tagment -> EDTA stop -> SDS/proteinase K -> SPRI |
| 3 linear amp | `ivt.py` | gap-fill (72 °C) -> T7 IVT (37 °C, ~17 h) -> RNA SPRI |
| 4 cDNA | `cdna.py` | random-hexamer RT -> RNase H -> second-strand -> SPRI |
| 5 library | `library.py` | ME-B Tn5 fragmentation -> PCR indexing -> 0.85× size-select |
| 6 QC | `qc.py` | Tecan dsDNA fluorescence quant + pass/dilute/fail gate |

Every volume, temperature, and incubation time lives in `config.py`, each traceable to the paper's Materials & Methods. Change the run there, not in the step code.

## The one honest caveat: FACS

`sciTIP-seq` combinatorial indexing requires a **FACS re-distribution of pooled cells between index 1 and index 2** - that's why the published sci method omits conA beads. **A STAR cannot sort cells.** So:

- **`plate_tipseq` / `bulk_tipseq`** keep cells on conA beads the whole way -> every separation is a magnet step -> **fully autonomous, one shot.** This is the recommended production path for up to 96 barcoded samples/targets in parallel.
- **`scitip_seq`** runs index-1 tagmentation on deck, then **stops at the FACS boundary**. On hardware it raises `FacsHandoffRequired`; an operator sorts the pool into the index-2 plate and calls `proto.resume_after_facs()`. In simulation it prints the boundary and continues so you can validate the whole flow.

This is a property of the assay, not the code. If you want a single-tube high-plex path with no sort, that's a protocol redesign (e.g. droplet or split-pool without live-cell sorting) - flagged, not hidden.

## Going live

`--simulate` is the default and everything above is real PyLabRobot API surface. To run on hardware:

1. `pip install "pylabrobot>=0.1.6"` and confirm the STAR/ODTC/HHS/reader versions you have.
2. In `deck.py`, pin the exact labware in `pin_labware()` to your inventory (tips, plates, reservoirs, magnet, black QC plate). The `_make_*` helpers fall back to generic geometry so the module always imports; a physical run should use your validated definitions.
3. Wire the two shim backends to your instruments:
   - `backends/inheco_odtc.py` -> map the friendly commands (`SetBlockTemperature`, `HoldTemperature`, lid actuation) to the ODTC's SiLA 2 feature set. PyLabRobot's first-party ODTC backend (forum PRs #841/#1026) can drop in here when released.
   - `backends/tecan_pro200.py` -> connect i-control/Magellan (SiLA or COM automation), or shell out to a headless exported method.
   - `devices.py::HeaterShakerDevice.setup` -> instantiate `HamiltonHeaterShakerBackend` or `InhecoThermoShakeBackend`.
4. Run with `--no-simulate` and your device addresses (`--` flags map to `RunConfig`: `odtc_host/port`, `hhs_com`, `tecan_host`).

Nothing about the biochemistry sequencing changes between sim and hardware - only the backend transport.

## Architecture

```
tipseq_plr/
  config.py          all parameters (volumes/temps/times), paper-traceable, no PLR import
  deck.py            STAR deck layout; labware pinning; version-tolerant fallbacks
  reagents.py        reagent -> reservoir map; prep-sheet planner; dead-volume guard
  devices.py         uniform async wrappers over STAR / HHS / ODTC / reader / magnet
  backends/
    inheco_odtc.py   SiLA-ready ODTC thermocycler backend (+ simulation)
    tecan_pro200.py  Tecan Infinite 200 Pro reader backend (+ simulation)
  steps/
    common.py        LiquidOps: column-wise pipetting, SPRI cleanup, magnet washes
    thermal.py       heater-shaker holds + ODTC ramp programs
    binding.py ... qc.py   the six stages
  protocol.py        TipSeqProtocol orchestrator (incl. FACS handoff)
  run.py             CLI
tests/               dry-mode smoke + logic tests
```

Design rules: step code never imports a vendor backend or branches on sim/real - it only calls `devices.py` wrappers and `LiquidOps`. Swapping an instrument is a one-line change in `build_devices`.

## Status

- ✅ End-to-end simulation of all three methods, 8-96 samples.
- ✅ Reagent prep sheet + labware checklist generation.
- ✅ dsDNA QC with standard-curve fit and pass/dilute/fail gating.
- 🔌 ODTC and Tecan backends are interface-complete shims; wire transports before a live run.
- 🧪 Not yet wet-lab validated. Treat as a method to dry-run, review, and adapt - not a validated SOP.

## License

MIT.
