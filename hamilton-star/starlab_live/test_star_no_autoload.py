import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck

async def main():
    print("🤖 Initializing Hamilton STAR via PyLabRobot from Raspberry Pi...")
    # Skip autoload init — it has a hardware issue we'll fix separately
    backend = STARBackend()
    lh = LiquidHandler(backend=backend, deck=STARDeck())
    await lh.setup(skip_autoload=True, skip_iswap=False)
    print("✅ STAR initialized (autoload skipped). Channels + iSWAP homed.")
    await lh.stop()
    print("🎉 Done. Arm is under Python control.")

asyncio.run(main())
