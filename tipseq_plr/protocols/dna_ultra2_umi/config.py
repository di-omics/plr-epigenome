"""
Parameters for an end-to-end NEBNext Ultra II DNA library prep with UMI adaptors
on a Hamilton STAR, with on-deck thermocycling (Inheco ODTC) and a Tecan
plate-reader QC readout that closes the loop on sequencing-ready libraries.

Numbers trace to NEB #E7645 / #E7103 (NEBNext Ultra II DNA Library Prep Kit for
Illumina, used with NEBNext Multiplex Oligos, Unique Dual Index UMI Adaptors),
Instruction Manual v2.0. Volumes are microliters, temperatures Celsius, times
SECONDS unless the field name says otherwise. No PyLabRobot imports here so
planners, cost models, and tests can read it without the hardware stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...config import Timings, QCThresholds


@dataclass
class EndPrep:
    """Section 1. End Prep reaction and its ODTC program."""

    dna_ul: float = 50.0
    buffer_ul: float = 7.0
    enzyme_ul: float = 3.0
    step1_c: float = 20.0
    step1_s: int = 30 * 60
    step2_c: float = 65.0
    step2_s: int = 30 * 60
    hold_c: float = 4.0
    lid_c: float = 75.0          # heated lid >= 75 C

    @property
    def total_ul(self) -> float:
        return self.dna_ul + self.buffer_ul + self.enzyme_ul   # 60


@dataclass
class Ligation:
    """Section 2. UMI adaptor ligation. Master mix is very viscous -> extra mix."""

    umi_adaptor_ul: float = 2.5
    ligation_mm_ul: float = 30.0
    ligation_enhancer_ul: float = 1.0
    incubation_c: float = 20.0
    incubation_s: int = 15 * 60
    lid_off: bool = True         # 20 C 15 min with the heated lid OFF
    mix_cycles: int = 12

    @property
    def total_ul(self) -> float:
        return 60.0 + self.umi_adaptor_ul + self.ligation_mm_ul + self.ligation_enhancer_ul  # 93.5


def adaptor_dilution(input_ng: float) -> tuple:
    """Table 2.1: (dilution label, working adaptor uM) by DNA input."""
    if input_ng > 100:
        return ("none", 20.0)     # 1 ug - 101 ng
    if input_ng >= 5:
        return ("1:10", 2.0)      # 100 - 5 ng
    return ("1:50", 0.4)          # < 5 ng


@dataclass
class Cleanup:
    """Section 3B. Cleanup without size selection (input <= 50 ng)."""

    spri_ratio: float = 0.7       # ~65 uL into 93.5 uL
    elution_ul: float = 22.0
    transfer_ul: float = 20.0
    etoh_washes: int = 2
    etoh_ul: float = 200.0


@dataclass
class SizeSelect:
    """Section 3A. Two-sided bead size selection (Table 2.3.1), 93.5 uL start.
    bead_table maps approximate insert size (bp) -> (first uL, second uL)."""

    bead_table: dict = field(default_factory=lambda: {
        150: (40.0, 20.0),
        200: (30.0, 15.0),
        300: (25.0, 10.0),
        400: (20.0, 10.0),
        550: (15.0, 10.0),
    })
    insert_bp: int = 150
    elution_ul: float = 22.0
    transfer_ul: float = 20.0
    etoh_washes: int = 2
    etoh_ul: float = 200.0


@dataclass
class PCR:
    """Section 4. Indexing PCR reaction and cycling profile."""

    input_ul: float = 20.0
    primer_mix_ul: float = 5.0
    q5_mm_ul: float = 25.0
    initial_denature: tuple = (98.0, 30)
    denature: tuple = (98.0, 10)
    anneal_extend: tuple = (65.0, 75)
    final_extend: tuple = (65.0, 300)
    hold_c: float = 4.0
    lid_c: float = 103.0          # heated lid >= 103 C

    @property
    def total_ul(self) -> float:
        return self.input_ul + self.primer_mix_ul + self.q5_mm_ul   # 50


def pcr_cycles_for(input_ng: float) -> int:
    """Table 4.1: PCR cycles for a standard library prep (~100 ng yield)."""
    for lo, cycles in ((500, 3), (100, 3), (50, 4), (10, 7), (5, 8), (1, 10)):
        if input_ng >= lo:
            return cycles
    return 11                     # 0.5 ng and below


@dataclass
class PcrCleanup:
    """Section 5. Cleanup of the PCR reaction."""

    spri_ratio: float = 0.8       # 40 uL into 50 uL
    elution_ul: float = 33.0
    transfer_ul: float = 30.0
    etoh_washes: int = 2
    etoh_ul: float = 200.0


@dataclass
class Ultra2Config:
    num_samples: int = 96
    input_ng: float = 100.0       # per-sample fragmented DNA input; drives adaptor dilution + PCR cycles
    size_select: bool = False     # False -> 0.7X cleanup; True -> two-sided size selection
    pcr_cycles_override: int = 0  # 0 -> derive from input_ng via Table 4.1
    simulate: bool = True

    # closed-loop QC -> pooling
    pool_target_ng_per_ul: float = 2.0
    pool_final_ul: float = 30.0

    # in-process CV error handling at the reader-blind steps (SPRI beads, tips).
    # Off by default; when on it aborts (or, monitor-only, just logs) on a fault.
    # vision_fault_at injects a fault at a named checkpoint for tests/demos.
    vision_enabled: bool = False
    vision_abort_on_fault: bool = True
    vision_fault_at: tuple = ()

    # device addressing (only used when simulate=False)
    star_id: str = "STAR"
    odtc_host: str = "192.168.1.50"
    odtc_port: int = 8080
    tecan_host: str = "192.168.1.60"

    endprep: EndPrep = field(default_factory=EndPrep)
    ligation: Ligation = field(default_factory=Ligation)
    cleanup: Cleanup = field(default_factory=Cleanup)
    sizeselect: SizeSelect = field(default_factory=SizeSelect)
    pcr: PCR = field(default_factory=PCR)
    pcr_cleanup: PcrCleanup = field(default_factory=PcrCleanup)
    timings: Timings = field(default_factory=Timings)      # bead_bind / bead_dry for SPRI
    qc: QCThresholds = field(default_factory=QCThresholds)  # pass/dilute/fail gates + read filters

    def cycles(self) -> int:
        return self.pcr_cycles_override or pcr_cycles_for(self.input_ng)
