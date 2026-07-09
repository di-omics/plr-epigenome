import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck


async def main():
    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(
        backend=STARBackend(),
        deck=STARDeck(),
    )

    try:
        await lh.setup(skip_autoload=True)
        print("STAR init completed with skip_autoload=True.")
    finally:
        print("Stopping / closing connection...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
