"""
Parameters for the plate-normalization protocol.

Flow: high-sensitivity Qubit dsDNA prep on an aliquot of each source well, read
on the Tecan, quantify against a standard curve, then normalize a 96-well plate
to a uniform concentration in a destination plate.

Source wells hold 12 uL. A small aliquot is consumed by the Qubit assay; the rest
is the material available to normalize. All volumes uL, concentrations ng/uL.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QubitHS:
    """Qubit dsDNA High Sensitivity assay, adapted to a black 96-well plate.

    Working solution (WS) = Qubit HS reagent diluted 1:200 in HS buffer. Per well
    we combine `sample_aliquot_ul` of sample with WS to `assay_volume_ul` total,
    incubate briefly at RT, and read fluorescence. Standards are prepared the same
    way (same aliquot into WS) from known dsDNA concentrations, so the curve maps
    RFU directly to the sample's original ng/uL.

    HS working range is ~0.01-100 ng/uL of assay input; with a 2 uL aliquot in
    200 uL that covers roughly 1-10,000 ng/uL of source before pre-dilution.
    """

    sample_aliquot_ul: float = 2.0
    assay_volume_ul: float = 200.0
    incubation_s: int = 120                 # 2 min RT
    excitation_nm: int = 485                # HS peak ~504/531; 485/530 filters read fine
    emission_nm: int = 530
    dye_ratio: str = "1:200"
    # known dsDNA standards (ng/uL of source-equivalent) loaded in the assay
    # standards column; 0 anchors background.
    standard_ng_per_ul: tuple = (0.0, 0.1, 0.5, 1.0, 5.0, 10.0, 25.0, 50.0)

    @property
    def ws_per_well_ul(self) -> float:
        return self.assay_volume_ul - self.sample_aliquot_ul


@dataclass
class NormConfig:
    num_samples: int = 96
    source_volume_ul: float = 12.0          # volume in each source well at start
    source_dead_ul: float = 1.0             # unaspirable residual per source well

    # normalization target
    target_ng_per_ul: float = 1.0           # uniform output concentration
    final_volume_ul: float = 20.0           # uniform output volume per dest well

    # liquid-handling limits (STAR CO-RE, 50 uL tips)
    min_transfer_ul: float = 1.0            # smallest reliable sample transfer
    max_transfer_ul: float = 45.0

    simulate: bool = True
    star_id: str = "STAR"
    tecan_host: str = "192.168.1.60"

    qubit: QubitHS = field(default_factory=QubitHS)

    @property
    def usable_source_ul(self) -> float:
        """Sample volume available to normalize after the Qubit aliquot + dead."""
        return self.source_volume_ul - self.qubit.sample_aliquot_ul - self.source_dead_ul
