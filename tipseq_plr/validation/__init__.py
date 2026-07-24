"""
Liquid-test validation framework.

The confidence ladder for plr-epigenome: a protocol goes from PLR-authored
(UNTESTED, simulation only), to LIQUID_TESTED (Rhodamine B accuracy + precision
verified on the STAR with paired plate-reader data, per the criteria in
`rhodamine.py`), to BIOVALIDATED (with biology; recorded in the configured
laboratory results system).

    from tipseq_plr.validation import evaluate, RhodamineCriteria, ValidationTier
"""

from .status import PROTOCOL_STATUS, ValidationTier, status_table, BIOLOGY_RECORDS_LOCATION
from .rhodamine import (
    RhodamineCriteria,
    Standard,
    Reading,
    VolumeTier,
    evaluate,
)

__all__ = [
    "ValidationTier",
    "PROTOCOL_STATUS",
    "status_table",
    "BIOLOGY_RECORDS_LOCATION",
    "RhodamineCriteria",
    "Standard",
    "Reading",
    "VolumeTier",
    "evaluate",
]
