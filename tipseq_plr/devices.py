"""
Device layer: uniform async wrappers over the four instruments this protocol
drives, plus a passive magnet controller.

Everything the step code touches goes through these wrappers, so the steps never
import a vendor backend directly and never branch on simulate/real. Swapping in a
real instrument is a one-line change in `build_devices`.

    lh      LiquidHandler  (Hamilton STAR, or chatterbox in simulation)
    hs      HeaterShakerDevice (Hamilton HHS / Inheco ThermoShake)
    tc      InhecoODTCBackend  (already async; used directly as the cycler)
    reader  TecanPro200Backend (dsDNA fluorescence quant)
    magnet  MagnetController   (passive nest; separation = move + settle)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from .backends import BDFACSMelodyBackend, InhecoODTCBackend, TecanPro200Backend
from .config import RunConfig

logger = logging.getLogger("tipseq.devices")


# ---------------------------------------------------------------------------
# Heater-shaker wrapper. Real backends: Hamilton HHS or Inheco ThermoShake.
# ---------------------------------------------------------------------------
class HeaterShakerDevice:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self._backend = None
        self._temp: Optional[float] = None
        self._rpm: int = 0

    async def setup(self):
        if self.cfg.simulate:
            logger.info("[sim] heater-shaker ready")
            return
        # Real path - pick the module you have installed:
        #   from pylabrobot.heating_shaking import HeaterShaker
        #   from pylabrobot.heating_shaking import HamiltonHeaterShakerBackend
        #   self._backend = HamiltonHeaterShakerBackend(index=..., com=self.cfg.hhs_com)
        # or InhecoThermoShakeBackend(...). Then await self._backend.setup().
        raise NotImplementedError(
            "Instantiate HamiltonHeaterShakerBackend/InhecoThermoShakeBackend here."
        )

    async def set_temperature(self, celsius: float):
        self._temp = celsius
        logger.info("HS set %.1fC", celsius)
        if not self.cfg.simulate:
            await self._backend.set_temperature(celsius)  # type: ignore

    async def wait_temperature(self, celsius: float, tolerance: float = 1.0):
        logger.info("HS wait for %.1fC", celsius)
        if self.cfg.simulate:
            return
        while abs((await self._backend.get_temperature()) - celsius) > tolerance:  # type: ignore
            await asyncio.sleep(5)

    async def shake(self, rpm: int):
        self._rpm = rpm
        logger.info("HS shake %d rpm", rpm)
        if not self.cfg.simulate:
            await self._backend.shake(speed=rpm)  # type: ignore

    async def stop_shake(self):
        self._rpm = 0
        logger.info("HS stop shake")
        if not self.cfg.simulate:
            await self._backend.stop_shaking()  # type: ignore

    async def stop(self):
        await self.stop_shake()
        if not self.cfg.simulate and self._backend is not None:
            await self._backend.stop()  # type: ignore


# ---------------------------------------------------------------------------
# Passive magnet: on a STAR the magnet is a fixed nest; "engage" just means the
# working plate has been moved onto it. We track state and expose a settle wait.
# ---------------------------------------------------------------------------
class MagnetController:
    def __init__(self, cfg: RunConfig, deckmap):
        self.cfg = cfg
        self.deckmap = deckmap
        self.engaged = False

    async def engage(self, lh, plate, settle_s: int = 180):
        """Move `plate` onto the magnet nest and let beads pellet."""
        logger.info("magnet: engage + settle %ss", settle_s)
        await _move_plate(lh, plate, self.deckmap.magnet_site, self.cfg.simulate)
        self.engaged = True
        await _sleep(settle_s, self.cfg)

    async def disengage(self, lh, plate, to_site=None):
        logger.info("magnet: disengage")
        dest = to_site if to_site is not None else self.deckmap.hhs_site
        await _move_plate(lh, plate, dest, self.cfg.simulate)
        self.engaged = False


@dataclass
class Devices:
    lh: object
    hs: HeaterShakerDevice
    tc: InhecoODTCBackend
    reader: TecanPro200Backend
    magnet: MagnetController
    cfg: RunConfig
    sorter: Optional[BDFACSMelodyBackend] = None   # BD FACSMelody, sci path only

    async def setup(self):
        if self.lh is not None:
            await self.lh.setup()
        await self.hs.setup()
        await self.tc.setup()
        await self.reader.setup()
        if self.sorter is not None:
            await self.sorter.setup()
        logger.info("all devices ready (simulate=%s, sorter=%s)",
                    self.cfg.simulate, self.sorter is not None)

    async def stop(self):
        for closer in (
            lambda: self.hs.stop(),
            lambda: self.tc.stop(),
            lambda: self.reader.stop(),
            lambda: self.sorter.stop() if self.sorter is not None else _noop(),
            lambda: self.lh.stop() if self.lh is not None else _noop(),
        ):
            try:
                await closer()
            except Exception as e:  # pragma: no cover
                logger.warning("shutdown warning: %s", e)


async def _noop():
    return None


async def _sleep(seconds: float, cfg: RunConfig):
    """Sleep, scaled down in simulation. Long IVT etc. become near-instant."""
    scale = getattr(cfg, "_sim_time_scale", 0.0)
    if cfg.simulate:
        if scale > 0 and seconds > 0:
            await asyncio.sleep(seconds * scale)
        return
    await asyncio.sleep(seconds)


async def _move_plate(lh, plate, destination, simulate: bool):
    if simulate or lh is None:
        logger.debug("[sim] move plate %s -> %s", getattr(plate, "name", plate), destination)
        return
    # Real STAR: iSWAP / CO-RE gripper plate move.
    await lh.move_plate(plate, destination)


def build_devices(cfg: RunConfig, deckmap) -> Devices:
    """Construct all device wrappers. In simulation the LiquidHandler uses the
    chatterbox backend (logs every atomic command); the cycler/reader use their
    own simulate flag."""
    lh = _build_liquid_handler(cfg, deckmap)
    hs = HeaterShakerDevice(cfg)
    tc = InhecoODTCBackend(
        host=cfg.odtc_host, port=cfg.odtc_port, simulate=cfg.simulate,
        sim_time_scale=getattr(cfg, "_sim_time_scale", 0.0),
    )
    reader = TecanPro200Backend(host=cfg.tecan_host, simulate=cfg.simulate)
    magnet = MagnetController(cfg, deckmap)
    sorter = None
    if cfg.sorter_enabled:
        sorter = BDFACSMelodyBackend(
            protocol_path=cfg.sorter_protocol_path or None,
            simulate=cfg.simulate,
            armed=cfg.sorter_armed,
            allow_actuation=cfg.sorter_allow_actuation,
            sort_template=cfg.sorter_template,
            sim_time_scale=getattr(cfg, "_sim_time_scale", 0.0),
        )
    return Devices(lh=lh, hs=hs, tc=tc, reader=reader, magnet=magnet, cfg=cfg, sorter=sorter)


def _build_liquid_handler(cfg: RunConfig, deckmap):
    try:
        from pylabrobot.liquid_handling import LiquidHandler
    except Exception as e:
        logger.warning("PyLabRobot not installed (%s); liquid handler is a no-op.", e)
        return None

    if cfg.simulate:
        from pylabrobot.liquid_handling.backends import LiquidHandlerChatterboxBackend
        backend = LiquidHandlerChatterboxBackend(num_channels=8)
    else:
        from pylabrobot.liquid_handling.backends import STARBackend
        backend = STARBackend()
    return LiquidHandler(backend=backend, deck=deckmap.deck)
