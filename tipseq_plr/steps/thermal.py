"""Temperature-step helpers shared by the biochemistry stages.

`incubate_hs` runs a fixed-temperature hold with shaking on the heater-shaker
(binding, tagmentation). `incubate_tc` runs an ordered ramp program on the ODTC
(gap-fill, RT, second-strand, fragmentation, PCR). Both move the working plate to
the right nest first.
"""

from __future__ import annotations

import logging
from typing import List

from ..backends import ProfileStep
from ..devices import _sleep

logger = logging.getLogger("tipseq.thermal")


async def incubate_hs(ops, celsius: float, seconds: float, rpm: int = 0, resuspend: bool = True):
    """Hold at temperature on the heater-shaker, optionally shaking."""
    await ops.to_heatershaker()
    await ops.dev.hs.set_temperature(celsius)
    await ops.dev.hs.wait_temperature(celsius)
    if rpm:
        await ops.dev.hs.shake(rpm)
    await _sleep(seconds, ops.cfg)
    if rpm:
        await ops.dev.hs.stop_shake()
    logger.info("HS incubation done: %.1fC / %ss", celsius, seconds)


async def incubate_tc(ops, steps: List[ProfileStep], lid_celsius: float = 105.0,
                      block_max_volume: float = 50.0):
    """Run a temperature program on the ODTC."""
    await ops.to_thermocycler()
    await ops.dev.tc.open_lid()
    # (plate is placed by the STAR; close lid and run)
    await ops.dev.tc.run_profile(steps, block_max_volume=block_max_volume, lid_celsius=lid_celsius)
    logger.info("ODTC program done: %d steps", len(steps))
