import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)

START_RAIL = 33
START_POS = 0

CLEANUP_RAIL = 40
CLEANUP_POS = 0

# Raise the modeled plate location so iSWAP grips higher.
# Try 3.0 first. If still too low, try 5.0, then 7.0.
ISWAP_PICKUP_Z_LIFT_MM = 3.0


def lift_resource_z(resource, dz_mm):
    loc = resource.location
    resource.location = Coordinate(loc.x, loc.y, loc.z + dz_mm)


async def main():
    print("Initializing STAR for iSWAP plate move test...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning carriers/resources...")

        start_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{START_RAIL}")
        cleanup_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{CLEANUP_RAIL}")

        lh.deck.assign_child_resource(start_carrier, rails=START_RAIL)
        lh.deck.assign_child_resource(cleanup_carrier, rails=CLEANUP_RAIL)

        work_plate = CellTreat_96_wellplate_350ul_Fb(name="work_plate")

        # Physical starting state: plate is on rail 33 pos 0.
        start_carrier[START_POS] = work_plate

        print(f"Original modeled plate location: {work_plate.location}")
        lift_resource_z(work_plate, ISWAP_PICKUP_Z_LIFT_MM)
        print(f"Raised modeled plate by {ISWAP_PICKUP_Z_LIFT_MM} mm")
        print(f"New modeled plate location: {work_plate.location}")

        print(f"Step 1: moving plate rail {START_RAIL} pos {START_POS} -> rail {CLEANUP_RAIL} pos {CLEANUP_POS}...")
        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, cleanup_carrier[CLEANUP_POS])

        print(f"Step 2: moving plate rail {CLEANUP_RAIL} pos {CLEANUP_POS} -> rail {START_RAIL} pos {START_POS}...")
        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, start_carrier[START_POS])

        print("SUCCESS: iSWAP plate move test completed.")
        print(f"Final expected physical location: rail {START_RAIL} pos {START_POS}")

    finally:
        print("Parking / stopping...")
        try:
            await lh.backend.park_iswap()
        except Exception as e:
            print(f"park_iswap warning: {e!r}")
        await lh.stop()
        print("Done.")


asyncio.run(main())
