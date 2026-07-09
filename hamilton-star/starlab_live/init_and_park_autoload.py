import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck

async def main():
    print("🤖 Init STAR (skip autoload during main setup)...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)
    print("✅ STAR connected.\n")
    
    backend = lh.backend
    
    print("🎯 Initializing autoload subsystem...")
    await backend.initialize_autoload()
    print("✅ Autoload initialized.\n")
    
    print("🎯 Parking autoload...")
    await backend.park_autoload()
    print("✅ Autoload parked.\n")
    
    await lh.stop()
    print("🎉 Done.")

asyncio.run(main())
