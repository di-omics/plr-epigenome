"""
Generic robot-arm backend: the physical bridge between instruments.

A PLR-driven arm that picks a piece of labware (a microfluidic chip, a tube rack,
a plate) from one instrument's nest and places it at another's. This is the
reusable connective tissue across the autonomous-lab stack: the same arm that
carries HyDrop co-encapsulation inputs to the Onyx also carries the index-2 plate
to the FACSMelody, or a plate between the STAR and the ODTC.

Design mirrors the other backends: sim mode logs the motion so the whole workflow
dry-runs; live mode is a thin adapter over a real arm SDK (Universal Robots RTDE,
Mecademic, or a ROS/MoveIt bridge), gated so it will not move a real arm unless
explicitly enabled.

Sites are named positions taught once on the physical cell (a dict of joint or
Cartesian waypoints). The backend only sequences approach -> grip -> retreat
between taught sites; it does not do motion planning here (leave that to the arm
controller or MoveIt).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("tipseq.arm")

try:
    from pylabrobot.machines.backend import MachineBackend  # type: ignore

    _BASE = MachineBackend
except Exception:  # pragma: no cover
    class _BASE:
        pass


@dataclass
class Site:
    """A taught transfer position (a nest the arm can pick from / place to)."""

    name: str
    instrument: str                 # "star", "onyx", "odtc", "melody", ...
    waypoint: dict = field(default_factory=dict)   # joints/pose, filled at teach time
    approach: dict = field(default_factory=dict)   # safe approach pose above the nest


class RobotArmBackend(_BASE):
    def __init__(
        self,
        *,
        kind: str = "generic",       # "ur" | "mecademic" | "ros" | "generic"
        host: str = "127.0.0.1",
        simulate: bool = True,
        enabled: bool = False,       # must be True to command a real arm
        speed_fraction: float = 0.25,  # cap speed near instruments
        sim_time_scale: float = 0.0,
    ):
        super().__init__()
        self.kind = kind
        self.host = host
        self.simulate = simulate
        self.enabled = enabled
        self.speed_fraction = max(0.01, min(speed_fraction, 1.0))
        self.sim_time_scale = sim_time_scale
        self.sites: Dict[str, Site] = {}
        self._holding: Optional[str] = None    # labware id currently gripped
        self._conn = None

    # -- lifecycle -----------------------------------------------------------
    async def setup(self):
        if self.simulate:
            logger.info("[sim] robot arm ready (kind=%s)", self.kind)
            return
        if not self.enabled:
            raise RuntimeError(
                "Live arm requires enabled=True. Keep it False until the cell is "
                "taught and interlocks are verified.")
        # Real adapters, wired per arm:
        #   ur:        ur_rtde.RTDEControlInterface(self.host)
        #   mecademic: mecademicpy.Robot(); connect(self.host)
        #   ros:       a MoveIt action client
        raise NotImplementedError(f"Wire the '{self.kind}' arm SDK here for live motion.")

    async def stop(self):
        if self._holding is not None:
            logger.warning("arm stopped while holding %s", self._holding)
        self._conn = None

    # -- teaching ------------------------------------------------------------
    def register_site(self, site: Site):
        self.sites[site.name] = site
        logger.debug("registered arm site %s @ %s", site.name, site.instrument)

    # -- motion primitives ---------------------------------------------------
    async def home(self):
        await self._motion("home")

    async def pick(self, site_name: str, labware_id: str):
        site = self._require(site_name)
        if self._holding is not None:
            raise RuntimeError(f"arm already holding {self._holding}; cannot pick {labware_id}")
        logger.info("arm: pick %s from %s (%s)", labware_id, site_name, site.instrument)
        await self._motion(f"approach:{site_name}")
        await self._motion(f"grip:{site_name}")
        self._holding = labware_id
        await self._motion(f"retreat:{site_name}")

    async def place(self, site_name: str):
        site = self._require(site_name)
        if self._holding is None:
            raise RuntimeError(f"arm holding nothing; cannot place at {site_name}")
        lw = self._holding
        logger.info("arm: place %s at %s (%s)", lw, site_name, site.instrument)
        await self._motion(f"approach:{site_name}")
        await self._motion(f"release:{site_name}")
        self._holding = None
        await self._motion(f"retreat:{site_name}")

    async def transfer(self, labware_id: str, from_site: str, to_site: str):
        """The one call the protocols use: move labware between two nests."""
        await self.pick(from_site, labware_id)
        await self.place(to_site)
        logger.info("arm: transferred %s  %s -> %s", labware_id, from_site, to_site)

    # -- internals -----------------------------------------------------------
    def _require(self, site_name: str) -> Site:
        if site_name not in self.sites:
            # in sim we tolerate untaught sites (create a stub) so dry-runs work
            if self.simulate:
                self.register_site(Site(name=site_name, instrument="unknown"))
            else:
                raise KeyError(f"arm site '{site_name}' not taught")
        return self.sites[site_name]

    async def _motion(self, step: str):
        if self.simulate or not self.enabled:
            logger.debug("[sim] arm motion: %s (speed %.0f%%)", step, self.speed_fraction * 100)
            if self.simulate and self.sim_time_scale > 0:
                await asyncio.sleep(1.0 * self.sim_time_scale)
            return
        raise NotImplementedError(f"execute motion '{step}' on the live arm")
