"""
Parameters for automated CUT&Tag.

CUT&Tag (Kaya-Okur et al. 2019) shares its entire front half with TIP-seq:
conA capture, primary + secondary antibody, pA-Tn5 binding, and tagmentation.
The difference is the tail: instead of T7 in-vitro transcription and cDNA
synthesis, the tagmented, purified gDNA goes straight into indexing PCR. The
pA-Tn5 here is loaded with standard ME-A/B adapters (not the ME-T7
transposon), which makes the material ready for PCR enrichment.

Volumes/times for the shared binding + tagmentation stages come from the shared
RunConfig (identical to TIP-seq). This config adds only the PCR tail. Values are
traceable to the CUT&Tag methods in Bartlett et al. 2021 (which reproduces
Kaya-Okur et al. 2019): 21 uL purified DNA + i5 + i7 + high-fidelity 2X master mix,
14-cycle indexing PCR, then a 1.1x SPRI cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CutAndTagConfig:
    num_samples: int = 96
    antibody_targets: tuple = ("H3K27me3", "H3K4me3", "H3K27ac", "CTCF")
    simulate: bool = True

    # SPRI ratios
    spri_ratio_purify: float = 2.0         # post-tagmentation gDNA cleanup
    spri_ratio_cleanup: float = 1.1        # post-PCR cleanup

    # indexing PCR (CUT&Tag: 12-15 cycles; 14 default)
    pcr_cycles: int = 14
    pcr_dna_ul: float = 21.0               # gDNA eluate volume feeding the PCR
    pcr_mastermix_ul: float = 25.0         # high-fidelity 2X PCR mix
    index_i5_ul: float = 2.0
    index_i7_ul: float = 2.0
    final_elution_ul: float = 30.0         # 10 mM Tris after post-PCR cleanup

    # device addressing (live only; shared machinery reads these via RunConfig)
    star_id: str = "STAR"
    odtc_host: str = "192.168.1.50"
    odtc_port: int = 8080
    hhs_com: str = "USB0"
    tecan_host: str = "192.168.1.60"

    def to_run_config(self):
        """Build the shared RunConfig the binding/tagmentation stages + LiquidOps
        consume. CUT&Tag reuses TIP-seq's buffer volumes/timings/temps verbatim."""
        from ...config import RunConfig, Method
        rc = RunConfig(
            method=Method.CUT_AND_TAG,
            num_samples=self.num_samples,
            antibody_targets=self.antibody_targets,
            simulate=self.simulate,
            pcr_cycles=self.pcr_cycles,
            star_id=self.star_id,
            odtc_host=self.odtc_host,
            odtc_port=self.odtc_port,
            hhs_com=self.hhs_com,
            tecan_host=self.tecan_host,
        )
        rc.volumes.spri_ratio_default = self.spri_ratio_purify
        setattr(rc, "_sim_time_scale", getattr(self, "_sim_time_scale", 0.0))
        return rc
