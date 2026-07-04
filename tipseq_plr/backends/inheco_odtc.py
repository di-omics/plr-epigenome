"""
Inheco ODTC (On-Deck Thermal Cycler) backend for PyLabRobot.

The ODTC exposes a SiLA 2 command interface (StartMethod / temperature control /
lid actuation). PLR's first-party ODTC backend was still in flight at time of
writing (forum thread + PRs #841/#1026), so this class targets PLR's
`ThermocyclerBackend` abstract interface and speaks to the device over SiLA when
`simulate=False`. In `simulate=True` it logs the program and advances a virtual
clock, so the whole protocol dry-runs with no hardware.

Interface implemented (async):
    setup / stop
    open_lid / close_lid
    set_block_temperature(celsius) / get_block_temperature
    set_lid_temperature(celsius)
    run_profile(steps, block_max_volume)   # steps = list[ProfileStep]
    deactivate_block / deactivate_lid
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("tipseq.odtc")

try:
    from pylabrobot.thermocycling.backend import ThermocyclerBackend  # type: ignore

    _BASE = ThermocyclerBackend
except Exception:  # pragma: no cover - PLR layout varies by version
    class _BASE:  # minimal stand-in so the class is instantiable everywhere
        pass


@dataclass
class ProfileStep:
    """One thermocycler hold. `cycles`>1 on a *group* is handled by run_profile."""

    celsius: float
    seconds: float
    name: str = ""


class InhecoODTCBackend(_BASE):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        *,
        simulate: bool = True,
        sim_time_scale: float = 0.0,
        insecure: bool = True,
    ):
        super().__init__()
        self.host = host
        self.port = port
        self.simulate = simulate
        # sim_time_scale: fraction of real wall time to actually sleep during
        # simulation (0.0 = instant, 1.0 = real time). Lets you smoke-test timing.
        self.sim_time_scale = sim_time_scale
        self.insecure = insecure
        self._client = None
        self._block_c: Optional[float] = None
        self._lid_c: Optional[float] = None
        self._lid_open = False

    # -- lifecycle -----------------------------------------------------------
    async def setup(self):
        if self.simulate:
            logger.info("[sim] ODTC ready at %s:%s", self.host, self.port)
            return
        # Real path: connect a SiLA 2 client and resolve the ODTC features.
        try:
            from sila2.client import SilaClient  # provided by the inheco/sila stack
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "SiLA client not installed. `pip install sila2` and point host/port "
                "at the ODTC server, or run with simulate=True."
            ) from e
        self._client = SilaClient(self.host, self.port, insecure=self.insecure)
        logger.info("ODTC connected: %s", self._client)

    async def stop(self):
        await self.deactivate_block()
        await self.deactivate_lid()
        self._client = None

    # -- lid -----------------------------------------------------------------
    async def open_lid(self):
        self._lid_open = True
        await self._cmd("OpenLid")

    async def close_lid(self):
        self._lid_open = False
        await self._cmd("CloseLid")

    async def set_lid_temperature(self, celsius: float):
        self._lid_c = celsius
        await self._cmd("SetLidTemperature", celsius)

    async def deactivate_lid(self):
        self._lid_c = None
        await self._cmd("DeactivateLid")

    # -- block ---------------------------------------------------------------
    async def set_block_temperature(self, celsius: float):
        self._block_c = celsius
        await self._cmd("SetBlockTemperature", celsius)

    async def get_block_temperature(self) -> float:
        if self.simulate:
            return self._block_c if self._block_c is not None else 25.0
        return float(await self._query("BlockTemperature"))

    async def deactivate_block(self):
        self._block_c = None
        await self._cmd("DeactivateBlock")

    # -- programs ------------------------------------------------------------
    async def run_profile(
        self,
        steps: List[ProfileStep],
        block_max_volume: float,
        lid_celsius: float = 105.0,
    ):
        """Execute an ordered list of holds. This is the primitive the higher
        level PCR/RT/gap-fill helpers compile down to."""
        await self.set_lid_temperature(lid_celsius)
        await self.close_lid()
        for s in steps:
            await self.set_block_temperature(s.celsius)
            await self._hold(s.celsius, s.seconds, s.name)
        logger.info("ODTC profile complete (%d steps)", len(steps))

    async def run_pcr(
        self,
        *,
        gapfill: Optional[ProfileStep],
        initial_denature: ProfileStep,
        denature: ProfileStep,
        anneal_extend: ProfileStep,
        cycles: int,
        final_extend: ProfileStep,
        hold_celsius: float,
        block_max_volume: float,
        lid_celsius: float = 105.0,
    ):
        steps: List[ProfileStep] = []
        if gapfill is not None:
            steps.append(gapfill)
        steps.append(initial_denature)
        for _ in range(cycles):
            steps.append(denature)
            steps.append(anneal_extend)
        steps.append(final_extend)
        await self.run_profile(steps, block_max_volume, lid_celsius)
        await self.set_block_temperature(hold_celsius)

    # -- internals -----------------------------------------------------------
    async def _hold(self, celsius: float, seconds: float, name: str):
        logger.info("ODTC hold %5.1fC for %6.0fs  (%s)", celsius, seconds, name or "-")
        if self.simulate:
            if self.sim_time_scale > 0 and seconds > 0:
                await asyncio.sleep(seconds * self.sim_time_scale)
            return
        # Real path: the ODTC SiLA method runs the hold; we poll until done.
        await self._cmd("HoldTemperature", celsius, seconds)

    async def _cmd(self, command: str, *args):
        if self.simulate:
            logger.debug("[sim] ODTC %s%s", command, args)
            return None
        # Map friendly command -> SiLA feature/command on the real client.
        # Names depend on the ODTC feature definition (FDL); wire them here.
        raise NotImplementedError(
            f"Wire SiLA command '{command}' to the ODTC feature set for live runs."
        )

    async def _query(self, prop: str):  # pragma: no cover
        raise NotImplementedError(f"Wire SiLA property '{prop}' for live runs.")
