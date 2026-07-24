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

PICKUP_OFFSET_X_MM = 0.0
PICKUP_OFFSET_Y_MM = 3.5
PICKUP_OFFSET_Z_MM = 40.0

DROPOFF_OFFSET_X_MM = 0.0
DROPOFF_OFFSET_Y_MM = 3.5
DROPOFF_OFFSET_Z_MM = 40.0


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
    print("Initializing STAR for corrected iSWAP offset test...")
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

        # Offset actual plate for initial pickup from rail 33.
        print(f"Original PICKUP plate location: {work_plate.location}")
        offset_location(
            work_plate,
            dx=PICKUP_OFFSET_X_MM,
            dy=PICKUP_OFFSET_Y_MM,
            dz=PICKUP_OFFSET_Z_MM,
        )
        print(
            "Applied PICKUP offset: "
            f"X={PICKUP_OFFSET_X_MM}, "
            f"Y={PICKUP_OFFSET_Y_MM}, "
            f"Z={PICKUP_OFFSET_Z_MM} mm"
        )
        print(f"Offset PICKUP plate location: {work_plate.location}")

        # Offset cleanup/magnet dropoff target for Step 1.
        cleanup_site = cleanup_carrier[CLEANUP_POS]
        print(f"Original CLEANUP DROPOFF site location: {cleanup_site.location}")
        offset_location(
            cleanup_site,
            dx=DROPOFF_OFFSET_X_MM,
            dy=DROPOFF_OFFSET_Y_MM,
            dz=DROPOFF_OFFSET_Z_MM,
        )
        print(
            "Applied CLEANUP DROPOFF offset: "
            f"X={DROPOFF_OFFSET_X_MM}, "
            f"Y={DROPOFF_OFFSET_Y_MM}, "
            f"Z={DROPOFF_OFFSET_Z_MM} mm"
        )
        print(f"Offset CLEANUP DROPOFF site location: {cleanup_site.location}")

        print(
            f"Step 1: moving plate rail {START_RAIL} pos {START_POS} "
            f"-> rail {CLEANUP_RAIL} pos {CLEANUP_POS}..."
        )
        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, cleanup_site)

        print("Step 1 completed: cleanup dropoff worked.")

        # After Step 1, rail 33 pos 0 is empty again.
        # CRITICAL: make and offset a real return dropoff target.
        return_site = start_carrier[START_POS]
        print(f"Original RETURN DROPOFF site location: {return_site.location}")
        offset_location(
            return_site,
            dx=DROPOFF_OFFSET_X_MM,
            dy=DROPOFF_OFFSET_Y_MM,
            dz=DROPOFF_OFFSET_Z_MM,
        )
        print(
            "Applied RETURN DROPOFF offset: "
            f"X={DROPOFF_OFFSET_X_MM}, "
            f"Y={DROPOFF_OFFSET_Y_MM}, "
            f"Z={DROPOFF_OFFSET_Z_MM} mm"
        )
        print(f"Offset RETURN DROPOFF site location: {return_site.location}")

        print(
            f"Step 2: moving plate rail {CLEANUP_RAIL} pos {CLEANUP_POS} "
            f"-> rail {START_RAIL} pos {START_POS}..."
        )
        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, return_site)

        print("SUCCESS: iSWAP 33 <-> 40 offset test completed.")
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
