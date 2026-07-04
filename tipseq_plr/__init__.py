"""
tipseq_plr - PyLabRobot automation of (sci)TIP-seq for Hamilton STAR.

Drives a Hamilton STAR with an Inheco ODTC on-deck thermocycler, a Hamilton
Heater-Shaker, and a Tecan Infinite 200 Pro reader for QC. Implements the
protocol from Bartlett et al. 2021 (J Cell Biol 220(12):e202103078).

Quick start (simulation, no hardware):

    from tipseq_plr import RunConfig, Method, TipSeqProtocol
    import asyncio

    cfg = RunConfig(method=Method.PLATE_TIPSEQ, num_samples=96, simulate=True)
    report = asyncio.run(TipSeqProtocol(cfg).run())
"""

from .config import (
    Method,
    RunConfig,
    Volumes,
    Timings,
    Temperatures,
    QCThresholds,
    PCRProfile,
)
from .protocol import TipSeqProtocol, FacsHandoffRequired

__all__ = [
    "Method",
    "RunConfig",
    "Volumes",
    "Timings",
    "Temperatures",
    "QCThresholds",
    "PCRProfile",
    "TipSeqProtocol",
    "FacsHandoffRequired",
]

__version__ = "0.1.0"
