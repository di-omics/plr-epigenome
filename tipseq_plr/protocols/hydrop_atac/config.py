"""
Parameters for HyDrop scATAC library prep with an Onyx droplet-generation step.

Traceable to the HyDrop ATAC methods in:
  De Rop et al. (2024) "Systematic benchmarking of single-cell ATAC-sequencing
  protocols." Nat Biotechnol 42:916-926. https://doi.org/10.1038/s41587-023-01881-x
  (HyDrop ATAC section), building on De Rop et al. (2022) eLife 11:e73971.

Volumes uL, temperatures C, times seconds unless noted. No PyLabRobot import so
planners and tests can use it freely.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Buffer / reagent names for HyDrop (assigned to reservoirs by the protocol).
ATAC_LYSIS = "hydrop_atac_lysis"          # BSA/Tris/NaCl/Tween/NP-40/MgCl2/Pitstop/digitonin
ATAC_WASH = "hydrop_atac_nuclei_wash"     # BSA/Tris/Tween/NaCl/MgCl2
PBS = "pbs"
ATAC_RXN_MIX = "hydrop_atac_reaction_mix" # DMF/Tris/MgCl2/Tn5/Pitstop/Tween/digitonin
LINAMP_PCR_MIX = "hydrop_linamp_pcr_mix"  # Phusion HF/OptiPrep/dNTP/DTT/Phusion/DeepVent/ET-SSB
HYDROP_BEADS = "hydrop_atac_beads"        # 384x384 barcoded hydrogel beads
HFE_OIL = "hfe7500_ea008_oil"             # HFE-7500 Novec oil + EA-008 surfactant
RECOVERY_AGENT = "recovery_agent"         # 20% perfluorooctanol in HFE-7500
GUSCN_BUFFER = "guscn_buffer"             # 5 M guanidinium thiocyanate / EDTA / Tris
DTT_1M = "dtt_1m"
DYNABEADS = "dynabeads_mytwo"             # streptavidin/DNA-binding Dynabeads
ETHANOL_80 = "ethanol_80"
ELUTION_BUFFER = "elution_buffer_dtt_tween"  # 10 mM Tris pH8.5 + 10 mM DTT + 0.1% Tween
AMPURE = "ampure_xp"
KAPA_HIFI = "kapa_hifi_2x"
INDEX_I5 = "index_i5_primer"
INDEX_I7 = "index_i7_primer"
QUANT_DYE = "dsdna_quant_dye"


@dataclass
class HyDropVolumes:
    lysis_ul: float = 200.0
    wash_ul: float = 1000.0
    pbs_resuspend_ul: float = 100.0
    reaction_mix_ul: float = 25.0          # per 25,000 nuclei tagmentation
    linamp_pcr_ul: float = 48.0            # added to 5,625 tagmented nuclei
    beads_ul: float = 35.0                 # HyDrop beads into co-encapsulation
    emulsion_target_ul: float = 100.0      # collected emulsion per sample
    # emulsion break (per 50 uL emulsion aliquot)
    recovery_agent_ul: float = 125.0
    guscn_ul: float = 55.0
    dtt_ul: float = 5.0
    dynabeads_ul: float = 5.0
    etoh_ul: float = 100.0
    dynabead_elution_ul: float = 50.0
    ampure_ratio_1: float = 1.0            # 1x Ampure after Dynabead elution
    ampure_elution_ul: float = 30.0
    index_pcr_ul: float = 100.0            # 1x KAPA HiFi + i5 + i7
    index_i5_ul: float = 2.0
    index_i7_ul: float = 2.0
    sizeselect_low: float = 0.4            # 0.4-1.2x double-sided Ampure
    sizeselect_high: float = 1.2
    final_elution_ul: float = 25.0


@dataclass
class HyDropTimings:
    lysis_s: int = 5 * 60                  # 5 min on ice
    tagmentation_s: int = 60 * 60          # 37C 1 h, no shaking
    emulsion_break_ice_s: int = 5 * 60
    dynabead_bind_s: int = 10 * 60
    bead_dry_s: int = 3 * 60


@dataclass
class HyDropTemps:
    ice: float = 4.0
    tagmentation: float = 37.0
    room_temp: float = 22.0


@dataclass
class LinAmpProfile:
    """HyDrop linear amplification after droplet generation (per paper):
    72C 15 min; 98C 3 min; 12x (98C 10s, 63C 30s, 72C 60s); hold 4C."""

    gapfill_c: float = 72.0
    gapfill_s: int = 15 * 60
    initial_denature_c: float = 98.0
    initial_denature_s: int = 3 * 60
    denature_c: float = 98.0
    denature_s: int = 10
    anneal_c: float = 63.0
    anneal_s: int = 30
    extend_c: float = 72.0
    extend_s: int = 60
    cycles: int = 12
    hold_c: float = 4.0


@dataclass
class IndexPCRProfile:
    """Index PCR with KAPA HiFi. Cycle count set by qPCR; default conservative."""

    denature_c: float = 98.0
    denature_s: int = 15
    anneal_c: float = 60.0
    anneal_s: int = 30
    extend_c: float = 72.0
    extend_s: int = 60
    cycles: int = 8


@dataclass
class HyDropConfig:
    num_samples: int = 8                   # HyDrop runs are low-N (one emulsion each)
    nuclei_per_reaction: int = 25000
    target_cells: int = 3000
    simulate: bool = True

    # Nuclei concentration/wash. The one spin HyDrop wants is here. A deck-
    # integrated VSpin keeps it on deck; set nuclei_preconcentrated=True to skip
    # it entirely when nuclei arrive already concentrated in the tagmentation
    # volume (dilution-quench lysis or an upstream prep).
    centrifuge_enabled: bool = True
    nuclei_preconcentrated: bool = False
    vspin_host: str = "COM5"
    spin_rcf_g: float = 500.0
    spin_seconds: int = 5 * 60
    spin_temperature_c: float = 4.0

    # device addressing (live only)
    star_id: str = "STAR"
    odtc_host: str = "192.168.1.50"
    odtc_port: int = 8080
    tecan_host: str = "192.168.1.60"
    onyx_host: str = "192.168.1.70"
    onyx_transport: str = "usb"
    arm_kind: str = "ur"                   # universal robots by default
    arm_host: str = "192.168.1.80"

    volumes: HyDropVolumes = field(default_factory=HyDropVolumes)
    timings: HyDropTimings = field(default_factory=HyDropTimings)
    temps: HyDropTemps = field(default_factory=HyDropTemps)
    linamp: LinAmpProfile = field(default_factory=LinAmpProfile)
    index_pcr: IndexPCRProfile = field(default_factory=IndexPCRProfile)

    # droplet-generation pressures (Onyx), tune per chip
    sample_pressure_mbar: float = 180.0
    bead_pressure_mbar: float = 200.0
    oil_pressure_mbar: float = 350.0
