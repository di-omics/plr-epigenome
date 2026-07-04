"""
Tecan Infinite 200 Pro (a.k.a. "Pro 200") plate-reader backend for PyLabRobot.

PLR ships CLARIOstar and Cytation reader backends but not Tecan, so this class
implements PLR's `PlateReaderBackend` interface for the Infinite 200 Pro. Live
control is typically driven through one of:

  * Tecan i-control / Magellan via the SiLA 2 or the .NET automation COM API, or
  * a headless run script exported from i-control that the STAR triggers.

We expose read_absorbance / read_fluorescence / read_luminescence returning a
list[list[float]] (row-major well grid). For TIP-seq QC we use fluorescence:
an intercalating dsDNA dye (PicoGreen-style) read at Ex 485 / Em 530, converted
to ng/uL against an on-plate standard curve by `qc.py`.

`simulate=True` synthesizes plausible readings so the QC gate logic can be
exercised offline.
"""

from __future__ import annotations

import logging
import random
from typing import List, Optional

logger = logging.getLogger("tipseq.tecan")

try:
    from pylabrobot.plate_reading.backend import PlateReaderBackend  # type: ignore

    _BASE = PlateReaderBackend
except Exception:  # pragma: no cover
    class _BASE:
        pass


class TecanPro200Backend(_BASE):
    def __init__(
        self,
        host: str = "127.0.0.1",
        *,
        simulate: bool = True,
        method_dir: Optional[str] = None,
        seed: Optional[int] = 7,
    ):
        super().__init__()
        self.host = host
        self.simulate = simulate
        self.method_dir = method_dir     # folder of exported i-control methods
        self._rng = random.Random(seed)
        self._client = None

    async def setup(self):
        if self.simulate:
            logger.info("[sim] Tecan Pro 200 ready (%s)", self.host)
            return
        raise NotImplementedError(
            "Connect to i-control/Magellan (SiLA or COM automation) here, or shell "
            "out to a headless i-control method. Run with simulate=True to dry-run."
        )

    async def stop(self):
        self._client = None

    # PLR PlateReader front-end calls these ---------------------------------
    async def open(self):
        logger.debug("Tecan tray out")

    async def close(self):
        logger.debug("Tecan tray in")

    async def read_absorbance(self, wavelength: int, **kwargs) -> List[List[float]]:
        return await self._read("absorbance", wavelength=wavelength)

    async def read_fluorescence(
        self, excitation_wavelength: int, emission_wavelength: int, **kwargs
    ) -> List[List[float]]:
        return await self._read(
            "fluorescence", ex=excitation_wavelength, em=emission_wavelength
        )

    async def read_luminescence(self, **kwargs) -> List[List[float]]:
        return await self._read("luminescence")

    # -----------------------------------------------------------------------
    async def _read(self, mode: str, **params) -> List[List[float]]:
        logger.info("Tecan read: %s %s", mode, params)
        if self.simulate:
            return self._simulated_plate(mode)
        raise NotImplementedError("Wire the live i-control read call here.")

    def _simulated_plate(self, mode: str) -> List[List[float]]:
        """8x12 grid. Column 12 (index 11) rows A-H emulate a dsDNA standard
        curve; the rest emulate libraries with mostly-good yields plus the
        occasional failed prep."""
        grid = []
        # standard curve RFUs roughly linear in ng: 0..50 ng -> ~50..40000 RFU
        std_ng = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0]
        for r in range(8):
            row = []
            for c in range(12):
                if c == 11:
                    base = 50 + std_ng[r] * 800
                    row.append(base + self._rng.uniform(-30, 30))
                else:
                    # library wells: mostly good yields, an occasional failed prep
                    conc = self._rng.choice([0.05] + [self._rng.uniform(2, 20)] * 8)
                    row.append(50 + conc * 800 + self._rng.uniform(-40, 40))
            grid.append(row)
        return grid
