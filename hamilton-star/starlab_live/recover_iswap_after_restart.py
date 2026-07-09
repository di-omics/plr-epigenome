import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck


async def main():
    print("Initializing STAR after restart...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Parking iSWAP...")
        await lh.backend.park_iswap()
        print("iSWAP parked successfully.")
    finally:
        print("Stopping / closing connection...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
