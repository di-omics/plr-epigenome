"""
Agilent/Inheco VSpin centrifuge backend.

The one spin HyDrop actually wants is concentrating/washing nuclei before
tagmentation (bare nuclei cannot be pelleted on a magnet). The VSpin is a
deck-integrated centrifuge the STAR iSWAP loads and unloads, so the whole step
stays on deck: gripper -> VSpin -> spin -> gripper back -> STAR aspirates the
supernatant off the pellet.

PyLabRobot has first-party VSpin support; this wraps it with a simulation path so
the workflow dry-runs, and falls back to a logging stub when PLR is absent.

A real VSpin needs its buckets balanced. `require_balance` makes the backend
refuse to spin unless a counterbalance was declared, so an unbalanced live run
fails loudly instead of on the rotor.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("tipseq.vspin")

try:
    from pylabrobot.centrifuge.backend import CentrifugeBackend  # type: ignore

    _BASE = CentrifugeBackend
except Exception:  # pragma: no cover - PLR layout varies / not installed
    class _BASE:
        pass


class VSpinBackend(_BASE):
    def __init__(
        self,
        *,
        host: str = "COM5",
        simulate: bool = True,
        require_balance: bool = True,
        sim_time_scale: float = 0.0,
    ):
        super().__init__()
        self.host = host
        self.simulate = simulate
        self.require_balance = require_balance
        self.sim_time_scale = sim_time_scale
        self._balanced = False
        self._real = None

    async def setup(self):
        if self.simulate:
            logger.info("[sim] VSpin ready")
            return
        # Real path: instantiate PLR's VSpin backend and open the loading door.
        #   from pylabrobot.centrifuge import VSpin
        #   self._real = VSpin(...); await self._real.setup()
        raise NotImplementedError("Wire PyLabRobot's VSpin backend here for live runs.")

    async def stop(self):
        self._real = None

    # -- door / loading ------------------------------------------------------
    async def open_door(self):
        await self._cmd("open_door")

    async def close_door(self):
        await self._cmd("close_door")

    async def lock_door(self):
        await self._cmd("lock_door")

    async def unlock_door(self):
        await self._cmd("unlock_door")

    async def lock_bucket(self):
        await self._cmd("lock_bucket")

    async def unlock_bucket(self):
        await self._cmd("unlock_bucket")

    async def go_to_bucket1(self):
        await self._cmd("go_to_bucket1")

    async def go_to_bucket2(self):
        await self._cmd("go_to_bucket2")

    def declare_balanced(self, counterbalance: bool = True):
        """Operator/loader asserts a counterbalance plate is in place."""
        self._balanced = counterbalance

    # -- spin ----------------------------------------------------------------
    async def spin(
        self,
        g: float,
        duration: float,
        acceleration: Optional[float] = None,
        *,
        temperature_c: Optional[float] = None,
    ):
        """Spin at ``g`` for ``duration`` seconds.

        The first three parameters match PyLabRobot's CentrifugeBackend
        interface. ``temperature_c`` is a VSpin-specific planning annotation
        retained for the simulated protocol path.
        """
        if self.require_balance and not self.simulate and not self._balanced:
            raise RuntimeError(
                "VSpin refused: buckets not declared balanced. Load a counterbalance "
                "and call declare_balanced(), or set require_balance=False.")
        temp = "" if temperature_c is None else f" @ {temperature_c:.0f}C"
        logger.info("VSpin: %.0f x g for %.0fs%s", g, duration, temp)
        await self.close_door()
        await self._cmd(
            "spin",
            g=g,
            duration=duration,
            acceleration=acceleration,
            temperature_c=temperature_c,
        )
        if self.simulate and self.sim_time_scale > 0:
            await asyncio.sleep(duration * self.sim_time_scale)
        await self.open_door()

    # -- internals -----------------------------------------------------------
    async def _cmd(self, command: str, **kw):
        if self.simulate:
            logger.debug("[sim] VSpin %s %s", command, kw or "")
            return None
        raise NotImplementedError(f"Wire VSpin command '{command}' for live runs.")
