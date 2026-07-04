"""
Protocol parameters for automated (sci)TIP-seq.

Every number here is traceable to the Materials & Methods of:

    Bartlett et al. (2021) "High-throughput single-cell epigenomic profiling by
    targeted insertion of promoters (TIP-seq)." J Cell Biol 220(12):e202103078.
    https://doi.org/10.1083/jcb.202103078

Volumes are microliters, temperatures Celsius, times seconds unless the field
name says otherwise. Keep this module free of PyLabRobot imports so it can be
imported by planners, cost models, and tests without any hardware stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Method(str, Enum):
    """Which flavor of the protocol to run.

    BULK_TIPSEQ and PLATE_TIPSEQ are fully deck-resident: cells stay on conA
    magnetic beads the whole way, so every separation is a magnet step the STAR
    can do. These run end-to-end without a human.

    SCITIP_SEQ adds combinatorial indexing. Index 1 is added on deck, but the
    published method then requires a FACS re-distribution between index 1 and
    index 2 (conA beads are omitted precisely so cells can be sorted). A STAR
    cannot sort cells, so this path pauses for an off-deck FACS handoff and then
    resumes. See protocol.py / README for the boundary.
    """

    BULK_TIPSEQ = "bulk_tipseq"
    PLATE_TIPSEQ = "plate_tipseq"
    SCITIP_SEQ = "scitip_seq"


@dataclass(frozen=True)
class Thermal:
    """A single hold: temperature for a duration. lid is the heated-lid target."""

    celsius: float
    seconds: float
    lid_celsius: float = 105.0
    name: str = ""


@dataclass(frozen=True)
class PCRProfile:
    """PCR indexing program (Materials & Methods, "Bulk TIP-seq" / "sciTIP-seq").

    Thermocycler program: 72C 5min gap-fill, 98C 30s initial denat, then
    `cycles` x (98C 10s, 63C 30s), 72C 1min final extension, hold at 8C.
    Optimal cycle count is set by qPCR per Buenrostro 2015 (7-12 typical).
    """

    gapfill = Thermal(72, 300, name="gap-fill")
    initial_denature = Thermal(98, 30, name="initial-denature")
    denature = Thermal(98, 10, name="denature")
    anneal_extend = Thermal(63, 30, name="anneal-extend")
    final_extend = Thermal(72, 60, name="final-extend")
    hold = Thermal(8, 0, lid_celsius=0, name="hold")
    cycles: int = 9


# ---------------------------------------------------------------------------
# Buffers / reagents. Names map 1:1 to the paper; `reagents.py` assigns each a
# physical trough/tube position on the deck.
# ---------------------------------------------------------------------------

WASH_BUFFER = "wash_buffer"            # 20mM HEPES pH7.5, 150mM NaCl, 0.5mM spermidine, PIC
ANTIBODY_BUFFER = "antibody_buffer"    # wash + 0.01% digitonin, 2mM EDTA, 1% BSA
DIG_WASH = "dig_wash"                  # wash + 0.01% digitonin
DIG_300 = "dig_300"                    # 0.01% dig, 20mM HEPES, 300mM NaCl, spermidine, PIC
TAG_BUFFER = "tag_buffer"              # Dig-300 + 10mM MgCl2
CONA_BEADS = "cona_beads"              # concanavalin-A magnetic beads (BP531)
SPRI_BEADS = "spri_beads"              # SPRI / SPRI-binding buffer (20% PEG-8000, 2.5M NaCl)
ETHANOL_80 = "ethanol_80"             # 80% EtOH wash
WATER = "nuclease_free_water"
EDTA_0_5M = "edta_0_5M"
SDS_10 = "sds_10pct"
PROTEINASE_K = "proteinase_k"          # 20 mg/ml
TAQ_5X = "taq_5x_mastermix"            # NEB M0285
T7_NTP = "t7_ntp"                      # 100 mM NTP set
T7_BUFFER = "t7_10x_buffer"
T7_POLYMERASE = "t7_polymerase_mix"    # HiScribe E2040
RNASE_INHIBITOR = "rnase_inhibitor"
RANDOM_HEXAMER = "random_hexamer"      # 20 uM
RT_BUFFER_5X = "rt_5x_buffer"          # SMART MMLV first-strand buffer
DNTP_10MM = "dntp_10mm"
DTT_100MM = "dtt_100mm"
MMLV_RT = "mmlv_rt"                    # SMART MMLV reverse transcriptase
RNASE_H = "rnase_h"
SSS_PRIMER = "second_strand_primer"    # sss_scnXTv2 / sss_sci-nXTv2
TAPS_BUFFER = "taps_buffer"
TN5_MEB = "tn5_me_b"                   # ME-B-only loaded Tn5, 0.7 uM
GUHCL = "guanidine_hcl"                # 4 M final
PCR_MASTERMIX = "nebnext_2x_pcr"       # NEB M0541
INDEX_I5 = "index_i5_primers"          # scT7_S5XX (sci) or Nextera i5
INDEX_I7 = "index_i7_primers"          # Nextera i7
QUANT_DYE = "dsdna_quant_dye"          # intercalating dsDNA dye for Tecan quant (e.g. PicoGreen)


@dataclass
class Volumes:
    """Reaction volumes (uL), straight from Materials & Methods."""

    cona_bead_slurry: float = 10.0
    antibody_reaction: float = 100.0       # primary Ab in antibody buffer
    secondary_reaction: float = 100.0      # secondary Ab in Dig-wash
    patn5_reaction: float = 100.0          # pA-Tn5 in Dig-300 (bulk); sci uses 50
    patn5_reaction_sci: float = 50.0
    wash_volume: float = 1000.0            # 1 ml washes in tube format
    wash_volume_plate: float = 180.0       # Dig-300 washes in 96-well sci format
    tagmentation: float = 100.0            # Tag buffer (bulk); sci uses 20
    tagmentation_sci: float = 20.0
    edta_stop: float = 3.3                 # 0.5 M EDTA to stop tagmentation (bulk)
    edta_stop_sci: float = 1.0
    sds: float = 2.0                       # 10% SDS -> 0.2% final
    proteinase_k: float = 0.84             # 20 mg/ml
    # gap-fill + IVT
    gapfill_water: float = 8.0
    taq_gapfill: float = 2.0
    t7_ntp: float = 2.0
    t7_buffer: float = 2.0
    t7_polymerase: float = 2.0
    rnase_inhibitor: float = 0.3
    rna_elution: float = 9.0
    # first-strand
    random_hexamer: float = 2.5
    rt_buffer_5x: float = 4.0
    dntp: float = 2.0
    dtt: float = 2.0
    mmlv_rt: float = 0.5
    rnase_h: float = 1.0
    # second-strand
    sss_primer: float = 2.5
    taq_second_strand: float = 5.9
    cdna_elution: float = 7.0
    # fragmentation
    taps_buffer: float = 2.0
    tn5_meb: float = 2.0
    guhcl_final_molar: float = 4.0
    frag_elution: float = 16.0
    # PCR indexing
    pcr_mastermix: float = 20.0
    index_i5: float = 2.0
    index_i7: float = 2.0
    pcr_total: float = 40.0
    # SPRI
    spri_ratio_default: float = 2.0        # 2.0x for RNA/cDNA/gDNA cleanups
    spri_ratio_sizeselect: float = 0.85    # left-side size selection (>200 bp)


@dataclass
class Timings:
    """Incubation times in SECONDS. IVT dominates wall-clock (16-19 h)."""

    cona_bind: int = 10 * 60
    primary_antibody: int = 12 * 3600      # overnight at 4C
    secondary_antibody: int = 60 * 60
    patn5_bind: int = 60 * 60
    wash_soak: int = 5 * 60
    tagmentation: int = 60 * 60
    edta_stop_soak: int = 15 * 60
    proteinase_k: int = 30 * 60            # 50C 30 min (or overnight 37C)
    gapfill: int = 3 * 60
    ivt: int = 17 * 3600                   # 16-19 h; use 17 h
    rt_anneal: int = 3 * 60                # 70C hexamer anneal
    rt_10: int = 10 * 60                   # 22C
    rt_60: int = 60 * 60                   # 42C
    rt_term: int = 10 * 60                 # 70C
    rnase_h: int = 20 * 60                 # 37C
    sss_anneal: int = 2 * 60               # 65C
    sss_extend: int = 8 * 60               # 72C
    fragmentation: int = 6 * 60            # 55C
    bead_bind: int = 5 * 60                # SPRI binding
    bead_dry: int = 3 * 60                 # EtOH evaporation


@dataclass
class Temperatures:
    """Setpoints (C)."""

    cold_storage: float = 4.0
    room_temp: float = 22.0
    binding: float = 22.0                  # antibody/pA-Tn5 binding at RT (primary is 4C)
    primary_antibody: float = 4.0
    tagmentation: float = 37.0
    proteinase_k: float = 50.0
    gapfill: float = 72.0
    ivt: float = 37.0
    rt_anneal: float = 70.0
    rt_step1: float = 22.0
    rt_step2: float = 42.0
    rt_term: float = 70.0
    rnase_h: float = 37.0
    sss_anneal: float = 65.0
    sss_extend: float = 72.0
    fragmentation: float = 55.0


@dataclass
class ShakeParams:
    """conA / antibody / bead incubations are done with gentle rotation; on a
    heater-shaker that maps to a low RPM to keep beads and cells suspended."""

    resuspend_rpm: int = 1000
    incubation_rpm: int = 500
    bead_mix_rpm: int = 1800


@dataclass
class QCThresholds:
    """Gates applied to Tecan quantification before a well is cleared for pooling.

    dsDNA concentration is read fluorometrically (intercalating dye) against a
    standard curve. Wells below `min_library_ng_per_ul` are flagged as failed
    library prep; wells above `saturation_ng_per_ul` are flagged for dilution.
    """

    min_library_ng_per_ul: float = 0.5
    saturation_ng_per_ul: float = 50.0
    standard_curve_ng: tuple = (0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0)
    excitation_nm: int = 485
    emission_nm: int = 530


@dataclass
class RunConfig:
    """Top-level knobs for one automation run."""

    method: Method = Method.PLATE_TIPSEQ
    num_samples: int = 96                  # wells processed in parallel
    cells_per_well: int = 2000             # sci index-1 loading
    antibody_targets: tuple = ("H3K27me3", "H3K27ac", "H3K9me3", "CTCF", "RNAPII-S2P")
    simulate: bool = True                  # chatterbox backends, no hardware I/O
    ivt_hours: float = 17.0
    pcr_cycles: int = 9
    # device network / addressing (only used when simulate=False)
    star_id: str = "STAR"
    odtc_host: str = "192.168.1.50"        # Inheco ODTC SiLA endpoint
    odtc_port: int = 8080
    hhs_com: str = "USB0"                  # Hamilton Heater Shaker node
    tecan_host: str = "192.168.1.60"       # Tecan Infinite 200 Pro / Spark

    # sciTIP-seq FACS sort (BD FACSMelody). When `sorter_enabled` is False the
    # sci run pauses at the FACS boundary (manual handoff, `resume_after_facs`).
    # When True, the sort is driven via the reverse-engineered ProtocolMap.
    sorter_enabled: bool = False
    sorter_protocol_path: str = ""         # decoded ProtocolMap from reverse_engineering/
    sorter_template: str = "sciTIP_singlet_deposit"
    sort_cells_per_well: int = 50          # 25-100 per paper; count-controlled deposition
    sorter_armed: bool = False             # must be True to open the live link
    sorter_allow_actuation: bool = False   # must be True to run fluidics/sort

    volumes: Volumes = field(default_factory=Volumes)
    timings: Timings = field(default_factory=Timings)
    temps: Temperatures = field(default_factory=Temperatures)
    shake: ShakeParams = field(default_factory=ShakeParams)
    qc: QCThresholds = field(default_factory=QCThresholds)
    pcr: PCRProfile = field(default_factory=PCRProfile)

    def __post_init__(self):
        object.__setattr__(self.pcr, "cycles", self.pcr_cycles)
