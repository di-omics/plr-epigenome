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

# WORKING iSWAP offsets.
# Apply same offset to every pickup/dropoff target.
OFFSET_X_MM = 0.0
OFFSET_Y_MM = 3.5
OFFSET_Z_MM = 40.0


def offset_location(resource, dx=0.0, dy=0.0, dz=0.0):
    loc = resource.location
    if loc is None:
        raise RuntimeError(
            f"{resource.name} has no location. "
            "This usually means it was not assigned to a carrier/site yet."
        )

    resource.location = Coordinate(
        loc.x + dx,
        loc.y + dy,
        loc.z + dz,
    )


async def main():
    print("Initializing STAR for no-pause iSWAP 33 -> 40 -> 33 test...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning carriers/resources...")

        start_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{START_RAIL}")
        cleanup_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{CLEANUP_RAIL}")

        lh.deck.assign_child_resource(start_carrier, rails=START_RAIL)
        lh.deck.assign_child_resource(cleanup_carrier, rails=CLEANUP_RAIL)

        work_plate = CellTreat_96_wellplate_350ul_Fb(name="work_plate")

        # Physical starting state:
        # rail 33 pos 0: plate present
        # rail 40 pos 0: empty
        start_carrier[START_POS] = work_plate

        print("\n=== OFFSETS ===")
        print(f"X={OFFSET_X_MM}, Y={OFFSET_Y_MM}, Z={OFFSET_Z_MM} mm")

        # STEP 1 PICKUP: offset actual plate on rail 33.
        print("\nPreparing Step 1 pickup from rail 33 pos 0...")
        print(f"Original plate location: {work_plate.location}")
        offset_location(work_plate, OFFSET_X_MM, OFFSET_Y_MM, OFFSET_Z_MM)
        print(f"Offset plate pickup location: {work_plate.location}")

        # STEP 1 DROPOFF: offset cleanup site on rail 40.
        cleanup_site = cleanup_carrier[CLEANUP_POS]
        print("\nPreparing Step 1 dropoff to rail 40 pos 0...")
        print(f"Original cleanup site location: {cleanup_site.location}")
        offset_location(cleanup_site, OFFSET_X_MM, OFFSET_Y_MM, OFFSET_Z_MM)
        print(f"Offset cleanup dropoff location: {cleanup_site.location}")

        print(f"\nStep 1: moving rail {START_RAIL} pos {START_POS} -> rail {CLEANUP_RAIL} pos {CLEANUP_POS}...")
        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, cleanup_site)

        print("Step 1 complete.")

        # STEP 2 PICKUP: work_plate is now at the already-offset cleanup site.
        print(f"\nStep 2 pickup location should be current plate location: {work_plate.location}")

        # STEP 2 DROPOFF: get empty rail 33 site AFTER Step 1, then offset it.
        return_site = start_carrier[START_POS]
        print("\nPreparing Step 2 dropoff back to rail 33 pos 0...")
        print(f"Original return site location: {return_site.location}")
        offset_location(return_site, OFFSET_X_MM, OFFSET_Y_MM, OFFSET_Z_MM)
        print(f"Offset return dropoff location: {return_site.location}")

        print(f"\nStep 2: moving rail {CLEANUP_RAIL} pos {CLEANUP_POS} -> rail {START_RAIL} pos {START_POS}...")
        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, return_site)

        print("\nSUCCESS: iSWAP no-pause 33 -> 40 -> 33 test completed.")
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
