"""
In-process computer-vision error handling for deck steps.

The plate-reader QC (steps/qc.py) is a terminal, per-well OUTCOME gate: it tells
you at the END whether a library formed. It cannot say WHY a well failed, and it
cannot catch a mechanical fault in time to stop the run. That is what this layer
is for: a small set of visual checkpoints at the steps where the plate reader is
blind, above all SPRI bead handling and tip pickup.

    reader QC   is the chemistry right?   terminal, per-well, lagging
    vision      is the step executing?     in-process, per-step, real time

Checkpoints are named and pluggable. In simulation there is no camera, so the
SimVision backend returns OK deterministically, and can inject a fault at a named
checkpoint to exercise the error-handling path (plant-and-recover). Real
inspection drops in behind the same interface via LabCvVision, which calls the
di-omics/lab-cv detector stack. Nothing here needs a camera to run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set

logger = logging.getLogger("tipseq.vision")

# checkpoint names: the reader-blind, failure-prone moments
CHECK_TIPS = "tips_present"                  # tips actually picked up on the channels
CHECK_BEAD_PELLET = "bead_pellet_formed"     # beads pelleted on the magnet, not lost
CHECK_SUPERNATANT = "supernatant_removed"    # supernatant cleared without pulling beads
CHECK_NOT_OVERDRIED = "beads_not_overdried"  # beads glossy, not cracked (over-dry drops recovery)
CHECK_LABWARE = "labware_seated"             # right plate, seated on the nest


class VisionFault(Exception):
    """A critical visual checkpoint failed; the run should stop or flag."""


@dataclass
class VisionVerdict:
    checkpoint: str
    ok: bool
    detail: str = ""
    column: Optional[int] = None


class SimVision:
    """Deterministic simulated inspector. No camera. Returns OK unless a
    checkpoint is named in `fault_at`, which lets tests and demos exercise the
    error-handling path with no hardware."""

    def __init__(self, fault_at: Optional[Iterable[str]] = None):
        self.fault_at: Set[str] = set(fault_at or ())

    async def inspect(self, checkpoint: str, *, column: Optional[int] = None, **ctx) -> VisionVerdict:
        if checkpoint in self.fault_at:
            return VisionVerdict(checkpoint, ok=False,
                                 detail="simulated fault (injected)", column=column)
        return VisionVerdict(checkpoint, ok=True, column=column)


class LabCvVision:  # pragma: no cover - optional real-model seam
    """Real inspection behind the same interface, backed by di-omics/lab-cv (a
    classical detector or a learned RF-DETR / SAM2 model on a deck camera)."""

    def __init__(self, camera: str = "deck_cam"):
        self.camera = camera

    async def inspect(self, checkpoint: str, *, column: Optional[int] = None, **ctx) -> VisionVerdict:
        raise RuntimeError(
            "Live CV inspection needs the di-omics/lab-cv detector stack and a deck "
            "camera. Map each checkpoint to a lab-cv detector (bead pellet "
            "present/absent, tips present, beads glossy vs cracked) and return a "
            "VisionVerdict. SimVision runs everywhere with no camera."
        )


@dataclass
class VisionChecks:
    """Runs checkpoints against a backend and keeps a verdict log. A failed
    critical checkpoint raises VisionFault so the caller can stop or flag; with
    abort_on_fault False the checkpoint is monitor-only (logged, run continues)."""

    backend: object
    abort_on_fault: bool = True
    log: List[VisionVerdict] = field(default_factory=list)

    async def check(self, checkpoint: str, *, column: Optional[int] = None, **ctx) -> VisionVerdict:
        v = await self.backend.inspect(checkpoint, column=column, **ctx)
        self.log.append(v)
        where = f" col{v.column + 1}" if v.column is not None else ""
        logger.info("[cv] %-22s %s%s%s", checkpoint, "OK" if v.ok else "FAULT",
                    where, f" ({v.detail})" if v.detail else "")
        if not v.ok and self.abort_on_fault:
            raise VisionFault(f"{checkpoint}{where}: {v.detail}")
        return v

    @property
    def faults(self) -> List[VisionVerdict]:
        return [v for v in self.log if not v.ok]


def build_vision(enabled: bool, *, fault_at: Optional[Iterable[str]] = None,
                 abort_on_fault: bool = True, simulate: bool = True) -> Optional[VisionChecks]:
    """Factory. None when disabled (no checks run); SimVision in simulation;
    LabCvVision on hardware."""
    if not enabled:
        return None
    backend = SimVision(fault_at=fault_at) if simulate else LabCvVision()
    return VisionChecks(backend=backend, abort_on_fault=abort_on_fault)
