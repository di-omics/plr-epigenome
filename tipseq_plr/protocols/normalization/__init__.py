"""
Plate normalization: Qubit HS quant -> Tecan read -> normalize a 96-well plate.

    from tipseq_plr.protocols.normalization import NormConfig, PlateNormalization
    import asyncio
    cfg = NormConfig(num_samples=96, source_volume_ul=12.0,
                     target_ng_per_ul=1.0, final_volume_ul=20.0, simulate=True)
    report = asyncio.run(PlateNormalization(cfg).run())
"""

from .config import NormConfig, QubitHS
from .plan import WellNorm, build_plan, plan_well, summarize
from .protocol import PlateNormalization

__all__ = [
    "NormConfig",
    "QubitHS",
    "WellNorm",
    "build_plan",
    "plan_well",
    "summarize",
    "PlateNormalization",
]
