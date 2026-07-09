import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck

async def main():
    print("🤖 Initializing Hamilton STAR via PyLabRobot from Raspberry Pi...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup()
    print("✅ STAR initialized. Channels + iSWAP homed.")
    await lh.stop()
    print("🎉 Done. Arm is under Python control.")

asyncio.run(main())
