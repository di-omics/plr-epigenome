import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck

HOVER_X_MM = 600
HOVER_Y_MM = 200
HOVER_Z_MM = 200

async def main():
    print("Init STAR...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)
    backend = lh.backend

    print("Clearing other components...")
    await backend.position_components_for_free_iswap_y_range()

    print(f"Moving iSWAP to ({HOVER_X_MM}, {HOVER_Y_MM}, {HOVER_Z_MM}) mm...")
    await backend.move_iswap_z(HOVER_Z_MM)
    await backend.move_iswap_x(HOVER_X_MM)
    await backend.move_iswap_y(HOVER_Y_MM)
    print("iSWAP positioned. Holding 5 seconds...")
    await asyncio.sleep(5)

    print("Parking iSWAP...")
    await backend.park_iswap()

    await lh.stop()
    print("Done.")

asyncio.run(main())
