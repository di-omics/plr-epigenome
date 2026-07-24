# HyDrop scATAC on the STAR, with an Onyx droplet-generation bridge

This protocol automates HyDrop single-cell ATAC library prep by pairing a Hamilton
STAR (all the wet chemistry) with a Droplet Genomics / Atrandi **Onyx** (droplet
generation), connected by a **PLR-driven robot arm** that carries labware between
the two. The arm is the reusable inter-instrument bridge: the same abstraction
also handles the FACSMelody plate handoff.

Protocol basis: the HyDrop ATAC methods in
[De Rop et al., Nat Biotechnol 42:916-926 (2024)](https://doi.org/10.1038/s41587-023-01881-x),
building on [De Rop et al., eLife 11:e73971 (2022)](https://doi.org/10.7554/eLife.73971).
The key line: the linear-amplification PCR mix is "coencapsulated with 35 uL of
freshly thawed HyDrop ATAC beads in HFE-7500 Novec oil with EA-008 surfactant on
an Onyx microfluidics platform (Droplet Genomics)." Droplet Genomics is now
Atrandi Biosciences, so it is the same Onyx.

## The division of labor

```
  STAR (wet chemistry)            ARM (bridge)             ONYX (droplets)
  ------------------------        ------------             ----------------
  1 nuclei prep
  2 tagmentation (37C 1h)
  3 assemble co-encaps  --------> carry chip -----------> 4 co-encapsulate
    (aqueous + beads + oil)                                  water-in-oil emulsion
  5 linear amp (ODTC)   <-------- carry emulsion <--------   collect ~100 uL
  6 emulsion break + capture beads
  7 SPRI beads cleanup
  8 index PCR (ODTC)
  9 double-sided size select
 10 QC (Tecan)
```

The STAR never reaches into the Onyx and the Onyx never reaches the deck. The arm
picks the loaded droplet-generation chip from a taught nest on the STAR, places it
on the Onyx, and after generation carries the collected emulsion to the ODTC nest
for linear amplification. Everything else is standard STAR bead chemistry.

## Run it (simulation, no hardware)

```bash
python -m tipseq_plr.protocols.hydrop_atac.run --samples 8 --simulate -v
```

You will see the handoffs in the log: `arm: pick onyx_chip from star_transfer ->
place at onyx_load`, then `Onyx: generate droplets -> collected 100 uL`, then
`arm: ... emulsion_plate onyx_output -> odtc_nest`. All timings compress in
simulation.

```python
from tipseq_plr.protocols.hydrop_atac import HyDropConfig, HyDropATAC
import asyncio
report = asyncio.run(HyDropATAC(HyDropConfig(num_samples=8, simulate=True)).run())
```

## The two new backends

- **`backends/robot_arm.py` (`RobotArmBackend`)**: a generic PLR-driven arm over
  named, taught transfer sites. `transfer(labware, from_site, to_site)` is the one
  call the protocols use. Live motion is gated behind `enabled=True` and a speed
  cap; the SDK adapter (Universal Robots RTDE, Mecademic, or a ROS/MoveIt bridge)
  is a wire-up point, not motion planning.
- **`backends/droplet_genomics_onyx.py` (`OnyxBackend`)**: pressure-driven droplet
  generation over three inlets (aqueous sample, HyDrop beads, HFE oil). `run_hydrop`
  loads the chip, primes, generates to a target emulsion volume, and depressurizes.
  If the Onyx exposes no open API, produce a `ProtocolMap` with the
  `reverse_engineering/` toolkit and drive it the same way the FACSMelody backend
  does. `armed=True` gates real actuation.

## Going live

1. Teach the arm sites on your physical cell (`star_transfer`, `onyx_load`,
   `onyx_output`, `odtc_nest`) and fill each `Site.waypoint`.
2. Wire the arm SDK in `RobotArmBackend.setup` and set `arm_motion_enabled=True`.
3. Wire the Onyx control interface (or its reverse-engineered `ProtocolMap`) in
   `OnyxBackend`, set `onyx_armed=True`, and tune the per-inlet pressures per chip.
4. The one spin (nuclei wash/concentration, 500g) is handled on deck by an
   integrated **VSpin** (`backends/vspin.py`), loaded by the STAR gripper. It is
   enabled by default (`centrifuge_enabled=True`); set `nuclei_preconcentrated=True`
   to skip it when nuclei arrive already concentrated in the tagmentation volume.
   Wire PyLabRobot's VSpin backend in `VSpinBackend.setup`, and note the balance
   guard: a live spin refuses unless a counterbalance is declared.

## What is honest here

The biochemistry sequence and volumes are traceable to the paper. The arm, Onyx,
and VSpin backends are interface-complete shims with simulation, not yet wired to
hardware, and the workflow is not wet-lab validated. It is a dry-runnable,
reviewable method that drops onto a taught robotic cell once the backends are
connected. With the VSpin integrated (or `nuclei_preconcentrated=True`), the whole
workflow is deck-resident: no off-deck steps remain.
