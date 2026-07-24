# Operator-supplied method parameters

The Hamilton scripts load assay chemistry values at runtime from an
operator-approved local profile. STAR deck geometry, collision safeguards,
calibrated liquid-handling heights, offsets, blowout settings, and recovery
behavior remain defined in the scripts.

Before importing or running an assay script, set
`PLR_METHOD_PARAMETERS_FILE` to a local JSON file approved under the lab's
current SOP:

```text
export PLR_METHOD_PARAMETERS_FILE=/path/to/operator-profile.json
```

[`method-parameters.schema.json`](method-parameters.schema.json) defines the
accepted profile shape. Missing, non-numeric, non-finite, zero, or negative
liquid volumes fail before robot setup. Incubation durations may be zero only
where the schema and loader explicitly accept a non-negative value.

Run the existing deck-assignment check and chatterbox rehearsal before any
human-gated hardware run. The local method profile does not override hardware
calibration constants in the scripts.
