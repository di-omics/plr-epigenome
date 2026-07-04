"""
HyDrop scATAC library prep with an Onyx droplet-generation step, bridged to the
Hamilton STAR by a PLR-driven robot arm.

    from tipseq_plr.protocols.hydrop_atac import HyDropConfig, HyDropATAC
    import asyncio
    report = asyncio.run(HyDropATAC(HyDropConfig(num_samples=8, simulate=True)).run())
"""

from .config import HyDropConfig
from .protocol import HyDropATAC

__all__ = ["HyDropConfig", "HyDropATAC"]
