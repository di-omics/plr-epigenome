import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck

async def main():
    print("🤖 Init STAR (skip autoload init, we'll command it manually)...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)
    print("✅ STAR connected.")
    
    print("🎯 Commanding autoload to home position...")
    backend = lh.backend
    # STAR firmware command to park/home the autoload carrier
    await backend.park_autoload()
    print("✅ Autoload homed.")
    
    await lh.stop()
    print("🎉 Done.")

asyncio.run(main())
