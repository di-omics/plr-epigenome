# Validation and confidence

## The objective

plr-epigenome takes a protocol from PyLabRobot, makes it run on a **Hamilton STAR**,
and then offers **liquid-tested validation** so a user can trust it in the lab.
Simulation proves the *logic* of a method. It proves nothing about whether the
STAR physically delivers the volumes the code asks for. This framework closes
that gap and states, honestly and per protocol, how much evidence stands behind
each method.

## The confidence ladder

Every protocol occupies exactly one tier, and it only moves up by earning it.

| Tier | What it means | Evidence required |
|---|---|---|
| **UNTESTED** | PLR-authored, dry-runs in simulation. No physical evidence the STAR dispenses what the code says. | none (this is the starting point) |
| **LIQUID_TESTED** | Liquid-handling accuracy and precision verified on the STAR. A claim about **volumes**, not biology. | a Rhodamine B assay with paired plate-reader data that clears the success criteria below |
| **BIOVALIDATED** | The protocol produces the expected biological result (yield, QC, sequencing metrics). | tracked **privately**; deliberately **not in this public repo** |

Two rules make the ladder meaningful:

- **Everything ships as UNTESTED.** All four protocols currently run in simulation
  and carry no paired Rhodamine B evidence, so all four are UNTESTED. That is the
  honest label until data says otherwise.
- **Biovalidation is private.** Biovalidation records are kept out of this
  repository on purpose. The public code names the tier and where records live,
  never the biological data itself.

## Liquid test: Rhodamine B, success criteria

**Method.** Dispense known target volumes of a Rhodamine B stock into wells (each
brought to a common final volume), read fluorescence on the plate reader, and
back-calculate the delivered volume from a Rhodamine standard curve. Rhodamine B
is used because its signal is bright, stable, and linear in amount over a wide
range.

A protocol step is **LIQUID_TESTED only when, on the real STAR with paired plate-
reader data, every one of these holds** (implemented in
[`validation/rhodamine.py`](../tipseq_plr/validation/rhodamine.py)):

1. **Paired data.** Every dispensed well has a matching reader value, and each
   target volume has at least `min_replicates` wells (default 3). Missing pairs
   mean the run is incomplete, so it stays UNTESTED.
2. **In range.** Every reading sits inside the plate reader's linear range: above
   blank, below the top standard, and below the saturation ceiling. A reading out
   of range cannot be trusted, so the step is UNTESTED, not "tested but failed".
3. **Linearity.** The Rhodamine standard curve is linear, R^2 >= `min_r2`
   (default 0.995), with a positive slope.
4. **Accuracy.** Per target volume, `|mean delivered - target| / target` is within
   the tier tolerance.
5. **Precision.** Per target volume, the replicate CV is within the tier tolerance.

Tolerances loosen as volumes shrink, because sub-microliter handling is genuinely
harder. Defaults (tune to your instrument's validated spec before making claims):

| Target volume | Accuracy | CV |
|---|---|---|
| >= 10 uL | +/- 5% | <= 3% |
| 2 to 10 uL | +/- 10% | <= 5% |
| < 2 uL | +/- 15% | <= 8% |

There is **no partial credit**. "Liquid tested" means the bar was cleared with
Rhodamine B and paired reader data across the tested volumes. If any check fails,
the verdict is UNTESTED with the reasons listed.

## Running it

```bash
# the public status ladder (all UNTESTED today)
python -m tipseq_plr.validation.cli status

# evaluate a Rhodamine B dataset from a real STAR run
python -m tipseq_plr.validation.cli evaluate --data rhodamine_run.json
```

The dataset is the paired plate-reader data:

```json
{
  "standards": [{"volume_ul": 2, "rfu": 1950}, {"volume_ul": 20, "rfu": 19050}],
  "readings":  [{"well": "A1", "target_ul": 10, "rfu": 9600}, ...]
}
```

`evaluate` exits non-zero unless `liquid_tested` is true, so it can gate CI or a
release. Promote a protocol to LIQUID_TESTED in
[`validation/status.py`](../tipseq_plr/validation/status.py) only after this
passes on real STAR data, and record the dataset id next to it.

## What this is and is not

This is a **volume** claim: the STAR moves the right liquid, accurately and
reproducibly, within the plate reader's trustworthy range. It is the honest,
public half of validation. The **biology** claim (biovalidation) is a separate,
private tier and is not part of this repository.
