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

# WORKING iSWAP offsets from live testing.
# Apply to EVERY pickup/dropoff target.
OFFSET_X_MM = 0.0
OFFSET_Y_MM = 3.5
OFFSET_Z_MM = 40.0

MIN_SAFE_PICKUP_Z_MM = 30.0
MIN_SAFE_DROPOFF_Z_MM = 120.0


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


def assert_safe_pickup_z(label, resource):
    loc = resource.location
    if loc is None:
        raise RuntimeError(f"{label} has no location.")

    print(f"{label} final location: {loc}")

    if loc.z < MIN_SAFE_PICKUP_Z_MM:
        raise RuntimeError(
            f"{label} PICKUP Z IS TOO LOW: {loc}. "
            f"Expected z >= {MIN_SAFE_PICKUP_Z_MM}. Aborting before movement."
        )


def assert_safe_dropoff_z(label, resource):
    loc = resource.location
    if loc is None:
        raise RuntimeError(f"{label} has no location.")

    print(f"{label} final location: {loc}")

    if loc.z < MIN_SAFE_DROPOFF_Z_MM:
        raise RuntimeError(
            f"{label} DROPOFF Z IS TOO LOW: {loc}. "
            f"Expected z >= {MIN_SAFE_DROPOFF_Z_MM}. Aborting before movement."
        )


async def main():
    print("Initializing STAR for FINAL SAFE iSWAP test...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning carriers/resources...")

        start_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{START_RAIL}")
        cleanup_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{CLEANUP_RAIL}")

        lh.deck.assign_child_resource(start_carrier, rails=START_RAIL)
        lh.deck.assign_child_resource(cleanup_carrier, rails=CLEANUP_RAIL)

        work_plate = CellTreat_96_wellplate_350ul_Fb(name="work_plate")

        # Physical starting state must match this:
        # rail 33 pos 0: plate present
        # rail 40 pos 0: empty
        start_carrier[START_POS] = work_plate

        print("\n=== GLOBAL iSWAP OFFSET APPLIED EVERYWHERE ===")
        print(f"X={OFFSET_X_MM} mm, Y={OFFSET_Y_MM} mm, Z={OFFSET_Z_MM} mm")

        # ------------------------------------------------------------------
        # STEP 1 PICKUP: rail 33 pos 0
        # The actual plate location controls pickup from 33.
        # ------------------------------------------------------------------
        print("\n--- STEP 1 PICKUP TARGET: rail 33 pos 0 ---")
        print(f"Original pickup plate location: {work_plate.location}")
        offset_location(work_plate, OFFSET_X_MM, OFFSET_Y_MM, OFFSET_Z_MM)
        assert_safe_pickup_z("STEP 1 PICKUP", work_plate)

        # ------------------------------------------------------------------
        # STEP 1 DROPOFF: rail 40 pos 0
        # The cleanup site controls dropoff to 40.
        # ------------------------------------------------------------------
        cleanup_site = cleanup_carrier[CLEANUP_POS]
        print("\n--- STEP 1 DROPOFF TARGET: rail 40 pos 0 ---")
        print(f"Original cleanup dropoff site location: {cleanup_site.location}")
        offset_location(cleanup_site, OFFSET_X_MM, OFFSET_Y_MM, OFFSET_Z_MM)
        assert_safe_dropoff_z("STEP 1 DROPOFF", cleanup_site)

        print(
            f"\nREADY STEP 1: rail {START_RAIL} pos {START_POS} "
            f"-> rail {CLEANUP_RAIL} pos {CLEANUP_POS}"
        )
        input("Confirm: plate on 33/0, 40/0 empty, iSWAP empty. Press Enter for Step 1, Ctrl+C to abort...")

        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, cleanup_site)

        print("STEP 1 COMPLETE: plate should now be at rail 40 pos 0.")

        # ------------------------------------------------------------------
        # STEP 2 PICKUP: rail 40 pos 0
        # After Step 1, work_plate's location should be cleanup_site.
        # It should already be high because cleanup_site was offset.
        # Check it again before pickup.
        # ------------------------------------------------------------------
        print("\n--- STEP 2 PICKUP TARGET: rail 40 pos 0 ---")
        assert_safe_pickup_z("STEP 2 PICKUP", work_plate)

        # ------------------------------------------------------------------
        # STEP 2 DROPOFF: rail 33 pos 0
        # IMPORTANT: get the return site AFTER Step 1, when 33/0 is empty.
        # Then offset it before using it as the Step 2 dropoff target.
        # ------------------------------------------------------------------
        return_site = start_carrier[START_POS]
        print("\n--- STEP 2 DROPOFF TARGET: rail 33 pos 0 ---")
        print(f"Original return dropoff site location: {return_site.location}")
        offset_location(return_site, OFFSET_X_MM, OFFSET_Y_MM, OFFSET_Z_MM)
        assert_safe_dropoff_z("STEP 2 DROPOFF", return_site)

        print(
            f"\nREADY STEP 2: rail {CLEANUP_RAIL} pos {CLEANUP_POS} "
            f"-> rail {START_RAIL} pos {START_POS}"
        )
        input("Confirm Step 2 pickup/dropoff Z are high. Press Enter for Step 2, Ctrl+C to abort...")

        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, return_site)

        print("SUCCESS: iSWAP 33 <-> 40 FINAL SAFE offset test completed.")
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
