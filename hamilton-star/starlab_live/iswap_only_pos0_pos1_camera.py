import argparse
import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)

# iSWAP-only camera run.
# No tips. No liquid. Just rail35 pos0 -> pos1 -> pos0.

LABWARE_RAIL = 35
WORK_POS = 0
MAG_POS = 1

ISWAP_OFFSET_X_MM = 0.0
ISWAP_OFFSET_Y_MM = 3.5
ISWAP_POS0_PICKUP_Z_MM = 19.0
ISWAP_POS1_DROPOFF_Z_MM = 40.0
ISWAP_POS1_PICKUP_Z_MM = 42.0
ISWAP_POS0_DROPOFF_Z_MM = 20.0


def offset_location(resource, dx=0.0, dy=0.0, dz=0.0):
    loc = resource.location
    if loc is None:
        raise RuntimeError(f"{resource.name} has no location.")
    resource.location = Coordinate(loc.x + dx, loc.y + dy, loc.z + dz)


def apply_iswap_pos0_pickup_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS0_PICKUP_Z_MM)


def apply_iswap_pos1_dropoff_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS1_DROPOFF_Z_MM)


def apply_iswap_pos1_pickup_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS1_PICKUP_Z_MM)


def apply_iswap_pos0_dropoff_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS0_DROPOFF_Z_MM)


async def assign_deck(lh):
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    work_plate = CellTreat_96_wellplate_350ul_Fb(name="iswap_camera_work_96wp")
    labware_carrier[WORK_POS] = work_plate

    print("Deck:")
    print("  rail35 pos0 = 96WP plate starts here")
    print("  rail35 pos1 = magnetic rack/dropoff site")
    print("")
    print("iSWAP offsets:")
    print(f"  pos0 pickup Z  = {ISWAP_POS0_PICKUP_Z_MM}")
    print(f"  pos1 dropoff Z = {ISWAP_POS1_DROPOFF_Z_MM}")
    print(f"  pos1 pickup Z  = {ISWAP_POS1_PICKUP_Z_MM}")
    print(f"  pos0 dropoff Z = {ISWAP_POS0_DROPOFF_Z_MM}")

    return {
        "labware_carrier": labware_carrier,
        "work_plate": work_plate,
    }


async def move_pos0_to_pos1(lh, r):
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]

    print("\n=== iSWAP CAMERA MOVE: rail35 pos0 -> rail35 pos1 ===")
    print(f"Original plate pickup location: {work_plate.location}")
    apply_iswap_pos0_pickup_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")

    mag_site = carrier[MAG_POS]
    original_mag_location = Coordinate(mag_site.location.x, mag_site.location.y, mag_site.location.z)

    print(f"Original pos1 dropoff site location: {mag_site.location}")
    apply_iswap_pos1_dropoff_offset(mag_site)
    print(f"Offset pos1 dropoff site location: {mag_site.location}")

    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, mag_site)

    mag_site.location = original_mag_location
    print("SUCCESS: iSWAP rail35 pos0 -> pos1 completed.")


async def move_pos1_to_pos0(lh, r):
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]

    print("\n=== iSWAP CAMERA MOVE: rail35 pos1 -> rail35 pos0 ===")
    print(f"Current plate pickup location before offset: {work_plate.location}")
    apply_iswap_pos1_pickup_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")

    work_site = carrier[WORK_POS]
    original_work_location = Coordinate(work_site.location.x, work_site.location.y, work_site.location.z)

    print(f"Original pos0 dropoff site location: {work_site.location}")
    apply_iswap_pos0_dropoff_offset(work_site)
    print(f"Offset pos0 dropoff site location: {work_site.location}")

    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, work_site)

    work_site.location = original_work_location
    print("SUCCESS: iSWAP rail35 pos1 -> pos0 completed.")


async def main():
    parser = argparse.ArgumentParser(description="iSWAP-only rail35 pos0/pos1 camera run.")
    parser.add_argument("--mode", choices=["deck", "run"], default="run")
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: no movement.")
            return

        await move_pos0_to_pos1(lh, r)
        await asyncio.sleep(2)
        await move_pos1_to_pos0(lh, r)

        print("\nSUCCESS: iSWAP-only camera run completed.")

    finally:
        print("Stopping STAR backend...")
        try:
            await lh.backend.park_iswap()
        except Exception as e:
            print(f"park_iswap warning: {e!r}")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
