"""
Automated CUT&Tag: TIP-seq's shared front half (conA -> antibodies -> pA-Tn5 ->
tagmentation) followed by direct indexing PCR instead of IVT/cDNA.

    from tipseq_plr.protocols.cut_and_tag import CutAndTagConfig, CutAndTag
    import asyncio
    report = asyncio.run(CutAndTag(CutAndTagConfig(num_samples=96, simulate=True)).run())
"""

from .config import CutAndTagConfig
from .protocol import CutAndTag

__all__ = ["CutAndTagConfig", "CutAndTag"]
