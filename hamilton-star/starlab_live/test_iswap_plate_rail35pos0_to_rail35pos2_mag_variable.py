import argparse
import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import PLT_CAR_L5AC_A00, Cor_96_wellplate_360ul_Fb

try:
    from pylabrobot.resources.coordinate import Coordinate
except ImportError:
    from pylabrobot.resources import Coordinate


RAIL = 35
PICKUP_POSITION = 0
DROP_POSITION = 2


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


async def main():
    parser = argparse.ArgumentParser(
        description="iSWAP isolated plate move test: rail35 pos0 -> rail35 pos2 magnetic rack/nest."
    )
    parser.add_argument("--mode", choices=["deck", "move"], default="deck")
    parser.add_argument("--pickup-z-offset-mm", type=float, default=8.5)
    parser.add_argument("--drop-x-offset-mm", type=float, default=0.0)
    parser.add_argument("--drop-y-offset-mm", type=float, default=0.0)
    parser.add_argument("--drop-z-offset-mm", type=float, default=18.0)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning rail35 carrier with pickup pos0 and mag drop pos2...")
        carrier = PLT_CAR_L5AC_A00(name="rail35_iswap_mag_test_carrier")
        lh.deck.assign_child_resource(carrier, rails=RAIL)

        pickup_plate = Cor_96_wellplate_360ul_Fb(
            name="iswap_pickup_plate_rail35_pos0",
            with_lid=False,
        )
        carrier[PICKUP_POSITION] = pickup_plate

        drop_site = carrier[DROP_POSITION]

        pickup_base = pickup_plate.location
        drop_base = drop_site.location

        pickup_plate.location = shifted(
            pickup_base,
            dz=args.pickup_z_offset_mm,
        )

        drop_site.location = shifted(
            drop_base,
            dx=args.drop_x_offset_mm,
            dy=args.drop_y_offset_mm,
            dz=args.drop_z_offset_mm,
        )

        print("")
        print("Deck map:")
        print(f"  pickup plate: rail{RAIL} pos{PICKUP_POSITION}")
        print(f"  drop site:    rail{RAIL} pos{DROP_POSITION} / magnetic rack")
        print(f"  pickup Z offset: +{args.pickup_z_offset_mm} mm")
        print(f"  drop X offset:   +{args.drop_x_offset_mm} mm")
        print(f"  drop Y offset:   +{args.drop_y_offset_mm} mm")
        print(f"  drop Z offset:   +{args.drop_z_offset_mm} mm")
        print("")
        print(f"  pickup base location:    {pickup_base}")
        print(f"  pickup shifted location: {pickup_plate.location}")
        print(f"  drop base location:      {drop_base}")
        print(f"  drop shifted location:   {drop_site.location}")
        print(f"  drop_site type:          {type(drop_site)}")
        print("")

        if args.mode == "deck":
            print("Mode deck: assignment/coordinate print only. No movement.")
            return

        if args.confirm != "RUN_ISWAP_MAG_MOVE_TEST":
            raise RuntimeError("Refusing to move. Add: --confirm RUN_ISWAP_MAG_MOVE_TEST")

        print("MOVING PLATE with iSWAP: rail35 pos0 -> rail35 pos2 magnetic rack/nest")
        print("Use EMPTY sacrificial plate. Destination mag rack/nest must be physically empty. Hand near E-stop.")

        async with lh.backend.slow_iswap():
            await lh.move_resource(pickup_plate, drop_site)

        print("SUCCESS: iSWAP moved plate from rail35 pos0 to rail35 pos2.")

    finally:
        print("Parking / stopping...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
