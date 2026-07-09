import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck

async def main():
    print("🤖 Init STAR (skipping autoload)... this will home channels + iSWAP")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)
    print("✅ STAR homed successfully.")
    await lh.stop()
    print("🎉 Done.")

asyncio.run(main())
