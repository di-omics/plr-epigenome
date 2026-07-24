"""
Confidence ladder for every protocol in this repo.

The objective of plr-epigenome: take a protocol from PyLabRobot, make it run on a
Hamilton STAR, and then offer *liquid-tested validation* so a user can trust it.
A protocol advances up this ladder only by earning it with data.

    UNTESTED       PLR-authored and dry-runs in simulation. No physical evidence
                   the STAR dispenses what the code says. This is where a protocol
                   starts and where it stays until a liquid test passes.

    LIQUID_TESTED  Accuracy and precision of the actual liquid handling verified
                   on the STAR with a Rhodamine B assay read on the plate reader,
                   with paired plate-reader data, meeting the success criteria in
                   `rhodamine.py`. This is a claim about *volumes*, not biology.

    BIOVALIDATED   The protocol produces the expected biological result (library
                   yield, QC, sequencing metrics). Validation records live in
                   the configured controlled laboratory record system. This
                   module carries only the record locator.

No protocol is BIOVALIDATED in the default configuration. Everything starts as
UNTESTED until a Rhodamine B dataset clears the bar; then it is marked
LIQUID_TESTED with a pointer to the paired dataset.
"""

from __future__ import annotations

from enum import Enum


class ValidationTier(str, Enum):
    UNTESTED = "untested"
    LIQUID_TESTED = "liquid_tested"
    BIOVALIDATED = "biovalidated"


# Current public status of each protocol. All UNTESTED: they run in simulation but
# have no paired Rhodamine B evidence yet. Promote a protocol here ONLY after
# `rhodamine.evaluate(...)` returns LIQUID_TESTED on real STAR data, and record the
# dataset id alongside it.
PROTOCOL_STATUS = {
    "tipseq":        {"tier": ValidationTier.UNTESTED, "liquid_dataset": None},
    "cut_and_tag":   {"tier": ValidationTier.UNTESTED, "liquid_dataset": None},
    "normalization":  {"tier": ValidationTier.UNTESTED, "liquid_dataset": None},
    "hydrop_atac":    {"tier": ValidationTier.UNTESTED, "liquid_dataset": None},
    "dna_library_umi": {"tier": ValidationTier.UNTESTED, "liquid_dataset": None},
}

# Biology records belong in the laboratory's configured controlled record
# system. This value describes the destination without carrying result payloads.
BIOLOGY_RECORDS_LOCATION = "configured controlled laboratory record system"


def status_table() -> str:
    """Render the public status ladder as a small text table."""
    rows = ["protocol        tier           liquid_dataset",
            "--------        ----           --------------"]
    for name, s in PROTOCOL_STATUS.items():
        rows.append(f"{name:15} {s['tier'].value:14} {s['liquid_dataset'] or '-'}")
    return "\n".join(rows)
