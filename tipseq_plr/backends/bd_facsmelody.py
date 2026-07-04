"""
BD FACSMelody sorter backend.

This is the runtime consumer of the reverse-engineering toolkit's output. It
loads a `ProtocolMap` (produced by `reverse_engineering/`), and drives the sort
step of sciTIP-seq: deposit a controlled number of gated singlets into each well
of the index-2 plate.

State of honesty:
  * `simulate=True` fakes the whole sort so the pipeline runs end-to-end today.
  * `simulate=False` requires a ProtocolMap in which the required commands are
    decoded. If they aren't, setup() fails loudly and tells you which RE stage is
    still missing - the backend never pretends to drive hardware it can't.

The command set the sort needs is the REQUIRED_COMMANDS list in the RE model:
connect, get_status, load_template, set_deposition, prime, start_sort,
wait_complete, abort, clean.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..reverse_engineering.model import ProtocolMap, seed_required
from ..reverse_engineering.replay import ReplayClient

logger = logging.getLogger("tipseq.melody")

try:
    from pylabrobot.machines.backend import MachineBackend  # type: ignore

    _BASE = MachineBackend
except Exception:  # pragma: no cover
    class _BASE:
        pass


class BDFACSMelodyBackend(_BASE):
    def __init__(
        self,
        protocol_path: Optional[str] = None,
        *,
        simulate: bool = True,
        armed: bool = False,
        allow_actuation: bool = False,
        sort_template: str = "sciTIP_singlet_deposit",
        sim_time_scale: float = 0.0,
    ):
        super().__init__()
        self.protocol_path = protocol_path
        self.simulate = simulate
        self.armed = armed
        self.allow_actuation = allow_actuation
        self.sort_template = sort_template
        self.sim_time_scale = sim_time_scale
        self.pm: Optional[ProtocolMap] = None
        self._client: Optional[ReplayClient] = None

    # -- lifecycle -----------------------------------------------------------
    async def setup(self):
        if self.simulate:
            self.pm = seed_required()
            logger.info("[sim] FACSMelody ready (protocol not required in simulation)")
            return
        if not self.protocol_path:
            raise RuntimeError(
                "Live FACSMelody needs a decoded ProtocolMap. Run the RE playbook "
                "(reverse_engineering/cli.py) and pass protocol_path=...")
        self.pm = ProtocolMap.from_json(self.protocol_path)
        cov = self.pm.coverage()
        if cov["missing"]:
            raise RuntimeError(
                f"ProtocolMap {self.protocol_path} is incomplete; undecoded "
                f"commands: {cov['missing']}. Finish RE decode before a live sort.")
        self._client = ReplayClient(
            self.pm.transport, self.pm.endpoint,
            armed=self.armed, allow_actuation=self.allow_actuation)
        self._client.open()
        logger.info("FACSMelody connected via %s @ %s", self.pm.transport.value, self.pm.endpoint)

    async def stop(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- command primitives --------------------------------------------------
    async def _cmd(self, command: str, live: bool = True, **params):
        if self.simulate:
            logger.info("[sim] Melody %s %s", command, params or "")
            await self._sleep(0.2)
            return b"OK"
        cmd = self.pm.commands[command]
        frame = cmd.frame_template
        for k, v in params.items():
            frame = frame.replace(f"{{{k}}}", _encode_param(v)) if frame else frame
        return self._client.send(command, frame, live=live)

    async def get_status(self) -> str:
        await self._cmd("get_status", live=True)
        return "idle" if self.simulate else "unknown"

    async def load_template(self, name: str):
        await self._cmd("load_template", name=name)

    async def set_deposition(self, cells_per_well: int, plate_format: str = "96"):
        await self._cmd("set_deposition", cells=cells_per_well, plate=plate_format)

    async def prime(self):
        await self._cmd("prime")

    async def start_sort(self, wells: int):
        await self._cmd("start_sort", wells=wells)

    async def wait_complete(self, poll_s: float = 5.0, timeout_s: float = 3600.0):
        if self.simulate:
            await self._sleep(30)  # a plate sort is minutes; compressed in sim
            return
        waited = 0.0
        while waited < timeout_s:
            if (await self.get_status()) in ("idle", "complete"):
                return
            await asyncio.sleep(poll_s)
            waited += poll_s
        raise TimeoutError("sort did not complete within timeout")

    async def abort(self):
        await self._cmd("abort")

    async def clean(self):
        await self._cmd("clean")

    # -- high-level orchestration -------------------------------------------
    async def sort_to_plate(self, *, cells_per_well: int, wells: int,
                            template: Optional[str] = None):
        """Full sort: gate template -> deposition config -> prime -> sort -> clean."""
        template = template or self.sort_template
        logger.info("Melody sort-to-plate: %d wells x %d cells (template=%s)",
                    wells, cells_per_well, template)
        await self.get_status()
        await self.load_template(template)
        await self.set_deposition(cells_per_well, plate_format="96")
        await self.prime()
        await self.start_sort(wells)
        await self.wait_complete()
        await self.clean()
        logger.info("Melody sort complete")

    async def _sleep(self, seconds: float):
        if self.sim_time_scale > 0 and seconds > 0:
            await asyncio.sleep(seconds * self.sim_time_scale)


def _encode_param(v) -> str:
    """Placeholder param encoder. The real byte encoding is discovered during RE
    (vary one parameter, diff the frames) and wired in here per parameter."""
    if isinstance(v, int):
        return f"{v & 0xFF:02x}"
    return str(v).encode().hex()
