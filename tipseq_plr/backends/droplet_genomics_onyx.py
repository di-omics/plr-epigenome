"""
Droplet Genomics / Atrandi Biosciences Onyx backend: droplet generation.

The Onyx is a pressure-driven microfluidics platform. For HyDrop scATAC it
co-encapsulates three inlet streams into a monodisperse water-in-oil emulsion:

    inlet A: aqueous sample  (tagmented nuclei + linear-amplification PCR mix)
    inlet B: barcoded HyDrop hydrogel beads (in suspension)
    inlet C: HFE-7500 Novec oil + EA-008 surfactant  (continuous phase)

Control is by per-inlet pressure (or flow) plus a generation duration; the run
ends when the target emulsion volume is collected. Like the FACSMelody, the Onyx
control surface may need reverse-engineering (reuse `reverse_engineering/`) if no
open API is exposed; this backend targets that interface and ships a simulation
so the whole HyDrop workflow dry-runs.

Safety: droplet generation itself is low-hazard, but it uses pressurized lines
and volatile fluorinated oil. `armed` gates any real actuation.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("tipseq.onyx")

try:
    from pylabrobot.machines.backend import MachineBackend  # type: ignore

    _BASE = MachineBackend
except Exception:  # pragma: no cover
    class _BASE:
        pass


@dataclass
class DropletParams:
    """One co-encapsulation recipe. Pressures in mbar (Onyx-style); tune per chip."""

    sample_pressure_mbar: float = 180.0
    bead_pressure_mbar: float = 200.0     # beads usually need a touch more push
    oil_pressure_mbar: float = 350.0
    target_emulsion_ul: float = 100.0
    max_duration_s: float = 900.0         # safety ceiling
    chip: str = "HyDrop-ATAC-50um"        # droplet-generation chip / nozzle size


class OnyxBackend(_BASE):
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        transport: str = "usb",           # "usb" | "serial" | "tcp" (confirm via RE)
        simulate: bool = True,
        armed: bool = False,
        sim_time_scale: float = 0.0,
    ):
        super().__init__()
        self.host = host
        self.port = port
        self.transport = transport
        self.simulate = simulate
        self.armed = armed
        self.sim_time_scale = sim_time_scale
        self._conn = None
        self._collected_ul = 0.0

    # -- lifecycle -----------------------------------------------------------
    async def setup(self):
        if self.simulate:
            logger.info("[sim] Onyx ready (transport=%s)", self.transport)
            return
        if not self.armed:
            raise RuntimeError("Live Onyx requires armed=True.")
        # Real path: open the control link. If the Onyx exposes no documented API,
        # produce a ProtocolMap with reverse_engineering/ and drive it the same way
        # the FACSMelody backend does.
        raise NotImplementedError(
            "Connect to the Onyx control interface (or a reverse-engineered "
            "ProtocolMap) here. Run with simulate=True to dry-run.")

    async def stop(self):
        await self.depressurize()
        self._conn = None

    # -- control primitives --------------------------------------------------
    async def load_chip(self, chip: str):
        logger.info("Onyx: load droplet-generation chip %s", chip)
        await self._cmd("load_chip", chip=chip)

    async def prime(self, params: DropletParams):
        """Fill inlets and establish stable co-flow before collecting product."""
        logger.info("Onyx: prime (sample %.0f / bead %.0f / oil %.0f mbar)",
                    params.sample_pressure_mbar, params.bead_pressure_mbar,
                    params.oil_pressure_mbar)
        await self._cmd("set_pressures",
                        sample=params.sample_pressure_mbar,
                        bead=params.bead_pressure_mbar,
                        oil=params.oil_pressure_mbar)
        await self._cmd("prime")

    async def generate(self, params: DropletParams) -> float:
        """Run droplet generation until the target emulsion volume is collected.
        Returns the collected volume (uL)."""
        logger.info("Onyx: generate droplets -> target %.0f uL (chip %s)",
                    params.target_emulsion_ul, params.chip)
        await self._cmd("start_generation")
        self._collected_ul = 0.0
        if self.simulate:
            # emulate ~ target reached well within the safety ceiling
            self._collected_ul = params.target_emulsion_ul
            await self._sleep(min(params.target_emulsion_ul * 2.0, params.max_duration_s))
        else:
            waited = 0.0
            while self._collected_ul < params.target_emulsion_ul and waited < params.max_duration_s:
                status = await self._query("status")   # expect collected volume, break-off ok
                self._collected_ul = float(status.get("collected_ul", 0.0))
                if not status.get("breakoff_stable", True):
                    logger.warning("Onyx: unstable break-off; consider re-priming")
                await asyncio.sleep(2.0)
                waited += 2.0
        await self._cmd("stop_generation")
        logger.info("Onyx: collected %.0f uL emulsion", self._collected_ul)
        return self._collected_ul

    async def depressurize(self):
        await self._cmd("depressurize")

    async def clean(self):
        logger.info("Onyx: flush / clean lines")
        await self._cmd("clean")

    # high-level one-call generation used by the protocol
    async def run_hydrop(self, params: DropletParams) -> float:
        await self.load_chip(params.chip)
        await self.prime(params)
        vol = await self.generate(params)
        await self.depressurize()
        return vol

    # -- internals -----------------------------------------------------------
    async def _cmd(self, command: str, **kw):
        if self.simulate:
            logger.debug("[sim] Onyx %s %s", command, kw or "")
            await self._sleep(0.2)
            return None
        raise NotImplementedError(f"Wire Onyx command '{command}' (API or RE ProtocolMap).")

    async def _query(self, prop: str) -> dict:  # pragma: no cover
        raise NotImplementedError(f"Wire Onyx query '{prop}' for live runs.")

    async def _sleep(self, seconds: float):
        if self.sim_time_scale > 0 and seconds > 0:
            await asyncio.sleep(seconds * self.sim_time_scale)
