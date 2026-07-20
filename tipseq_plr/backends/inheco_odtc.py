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
from typing import List, Optional, Sequence, Union

logger = logging.getLogger("tipseq.odtc")

try:
    from pylabrobot.thermocycling.backend import ThermocyclerBackend  # type: ignore
    from pylabrobot.thermocycling.standard import BlockStatus, LidStatus, Protocol

    _BASE = ThermocyclerBackend
except Exception:  # pragma: no cover - PLR layout varies by version
    BlockStatus = LidStatus = Protocol = object  # type: ignore

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
        self._profile_running = False
        self._current_step_index = 0
        self._total_step_count = 0
        self._current_cycle_index = 0
        self._total_cycle_count = 0
        self._hold_seconds = 0.0

    @staticmethod
    def _celsius(value: Union[float, Sequence[float]]) -> float:
        """Accept PLR's one-zone list form and this backend's scalar shorthand."""
        if isinstance(value, (int, float)):
            return float(value)
        if not value:
            raise ValueError("ODTC needs at least one temperature zone.")
        return float(value[0])

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

    async def set_lid_temperature(self, temperature: Union[float, Sequence[float]]):
        self._lid_c = self._celsius(temperature)
        await self._cmd("SetLidTemperature", self._lid_c)

    async def deactivate_lid(self):
        self._lid_c = None
        await self._cmd("DeactivateLid")

    # -- block ---------------------------------------------------------------
    async def set_block_temperature(self, temperature: Union[float, Sequence[float]]):
        self._block_c = self._celsius(temperature)
        await self._cmd("SetBlockTemperature", self._block_c)

    async def get_block_temperature(self) -> float:
        if self.simulate:
            return self._block_c if self._block_c is not None else 25.0
        return float(await self._query("BlockTemperature"))

    async def deactivate_block(self):
        self._block_c = None
        self._profile_running = False
        await self._cmd("DeactivateBlock")

    # -- PyLabRobot ThermocyclerBackend state -------------------------------
    # These methods keep the custom ODTC adapter compatible with the current
    # abstract PLR interface while retaining the simpler scalar helpers above.

    async def get_block_current_temperature(self) -> List[float]:
        return [await self.get_block_temperature()]

    async def get_block_target_temperature(self) -> List[float]:
        if self._block_c is None:
            raise RuntimeError("Block target temperature is not set.")
        return [self._block_c]

    async def get_lid_current_temperature(self) -> List[float]:
        return [self._lid_c if self._lid_c is not None else 25.0]

    async def get_lid_target_temperature(self) -> List[float]:
        if self._lid_c is None:
            raise RuntimeError("Lid target temperature is not set.")
        return [self._lid_c]

    async def get_lid_open(self) -> bool:
        return self._lid_open

    async def get_lid_status(self) -> LidStatus:
        return LidStatus.HOLDING_AT_TARGET if self._lid_c is not None else LidStatus.IDLE

    async def get_block_status(self) -> BlockStatus:
        return BlockStatus.HOLDING_AT_TARGET if self._block_c is not None else BlockStatus.IDLE

    async def get_hold_time(self) -> float:
        return self._hold_seconds if self._profile_running else 0.0

    async def get_current_cycle_index(self) -> int:
        return self._current_cycle_index

    async def get_total_cycle_count(self) -> int:
        return self._total_cycle_count

    async def get_current_step_index(self) -> int:
        return self._current_step_index

    async def get_total_step_count(self) -> int:
        return self._total_step_count

    # -- programs ------------------------------------------------------------
    async def run_profile(
        self,
        steps: List[ProfileStep],
        block_max_volume: float,
        lid_celsius: float = 105.0,
    ):
        """Execute an ordered list of holds. This is the primitive the higher
        level PCR/RT/gap-fill helpers compile down to."""
        self._profile_running = True
        self._total_step_count = len(steps)
        self._current_step_index = 0
        self._total_cycle_count = 1
        self._current_cycle_index = 1
        await self.set_lid_temperature(lid_celsius)
        await self.close_lid()
        for s in steps:
            self._current_step_index += 1
            self._hold_seconds = s.seconds
            await self.set_block_temperature(s.celsius)
            await self._hold(s.celsius, s.seconds, s.name)
        self._profile_running = False
        self._hold_seconds = 0.0
        logger.info("ODTC profile complete (%d steps)", len(steps))

    async def run_protocol(self, protocol: Protocol, block_max_volume: float):
        """Run a standard PyLabRobot protocol through the ODTC adapter."""
        steps: List[ProfileStep] = []
        for stage_index, stage in enumerate(protocol.stages, start=1):
            for repeat in range(stage.repeats):
                for step_index, step in enumerate(stage.steps, start=1):
                    steps.append(
                        ProfileStep(
                            celsius=self._celsius(step.temperature),
                            seconds=float(step.hold_seconds),
                            name=f"stage {stage_index}, repeat {repeat + 1}, step {step_index}",
                        )
                    )
        await self.run_profile(steps, block_max_volume)

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
