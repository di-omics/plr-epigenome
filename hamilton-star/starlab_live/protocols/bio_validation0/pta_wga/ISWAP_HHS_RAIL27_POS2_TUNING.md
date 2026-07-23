# iSWAP HHS rail27 pos2 tuning (Bio Validation 0, whole-genome sequencing)

Validated iSWAP plate-transfer offsets between the whole-genome sequencing work position
(**rail35 pos0**) and the Hamilton Heater Shaker (**HHS, rail27 pos2**).

Offsets below were confirmed on the live instrument. This is **dry / camera
choreography only** — move an EMPTY sacrificial plate, destination nest must be
physically empty, keep a hand near the E-stop. Do not change these geometries.

## Forward move: rail35 pos0 -> rail27 pos2 (work -> HHS)

Script: `test_iswap_plate_rail35pos0_to_rail27_variable.py`

| Offset | Value |
| --- | --- |
| pickup rail35 pos0 Z | +5.5 mm |
| drop rail27 pos2 X | +12.0 mm |
| drop rail27 pos2 Y | +54.5 mm |
| drop rail27 pos2 Z | +17.0 mm |

Requires `--mode move` plus the confirm token `RUN_ISWAP_PLATE_TEST` to move.

```
python protocols/bio_validation0/pta_wga/test_iswap_plate_rail35pos0_to_rail27_variable.py \
  --mode move \
  --drop-position 2 \
  --pickup-z-offset-mm 5.5 \
  --drop-x-offset-mm 12.0 \
  --drop-y-offset-mm 54.5 \
  --drop-z-offset-mm 17.0 \
  --confirm RUN_ISWAP_PLATE_TEST
```

## Return move: rail27 pos2 -> rail35 pos0 (HHS -> work)

Script: `test_iswap_plate_rail27pos2_hhs_to_rail35pos0_return.py`

| Offset | Value |
| --- | --- |
| pickup rail27 pos2 X | +12.0 mm |
| pickup rail27 pos2 Y | +54.5 mm |
| pickup rail27 pos2 Z | +9.0 mm |
| return drop rail35 pos0 Z | +8.5 mm |

The return script moves on execution (no `--mode`/`--confirm` gate). Its built-in
argument defaults are NOT the validated values, so the tuned offsets must be
passed explicitly on every run.

```
python protocols/bio_validation0/pta_wga/test_iswap_plate_rail27pos2_hhs_to_rail35pos0_return.py \
  --hhs-pickup-x-offset-mm 12.0 \
  --hhs-pickup-y-offset-mm 54.5 \
  --hhs-pickup-z-offset-mm 9.0 \
  --return-drop-z-offset-mm 8.5
```

## Full dry choreography

`protocols/bio_validation0/full_end_to_end/run_pta_hhs_iswap_then_targeted_pcr_dry_return_tips.py`
runs the forward move, then the return move, then the targeted PCR full built dry
choreography (`09_targeted_pcr_full_built_end_to_end_dry.py`). It refuses to run
without `--confirm RUN_FULL_PTA_TARGETED_PCR_DRY_RETURN_TIPS`.
