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


PICKUP_RAIL = 35
PICKUP_POSITION = 0

DROP_RAIL = 27
DROP_POSITION = 1


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


async def main():
    parser = argparse.ArgumentParser(
        description="iSWAP isolated plate move test: rail35 pos0 -> rail27 pos1 with adjustable offsets."
    )
    parser.add_argument("--mode", choices=["deck", "move"], default="deck")
    parser.add_argument("--pickup-z-offset-mm", type=float, default=10.0)
    parser.add_argument("--drop-x-offset-mm", type=float, default=0.0)
    parser.add_argument("--drop-y-offset-mm", type=float, default=23.0)
    parser.add_argument("--drop-z-offset-mm", type=float, default=0.0)
    parser.add_argument("--drop-position", type=int, default=1)
    parser.add_argument("--drop-position", type=int, default=1)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning pickup/drop carriers...")
        pickup_carrier = PLT_CAR_L5AC_A00(name=f"pickup_carrier_rail{PICKUP_RAIL}")
        drop_carrier = PLT_CAR_L5AC_A00(name=f"drop_carrier_rail{DROP_RAIL}")

        lh.deck.assign_child_resource(pickup_carrier, rails=PICKUP_RAIL)
        lh.deck.assign_child_resource(drop_carrier, rails=DROP_RAIL)

        pickup_plate = Cor_96_wellplate_360ul_Fb(
            name="iswap_pickup_plate_rail35_pos0",
            with_lid=False,
        )

        pickup_carrier[PICKUP_POSITION] = pickup_plate

        # IMPORTANT: destination is the empty carrier site/slot, not a fake plate.
        drop_site = drop_carrier[args.drop_position]

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
        print(f"  pickup plate: rail{PICKUP_RAIL} pos{PICKUP_POSITION}")
        print(f"  drop site:    rail{DROP_RAIL} pos{args.drop_position}")
        print(f"  pickup Z offset: +{args.pickup_z_offset_mm} mm")
        print(f"  drop X offset:   +{args.drop_x_offset_mm} mm")
        print(f"  drop Y offset:   +{args.drop_y_offset_mm} mm")
        print(f"  drop Z offset:   +{args.drop_z_offset_mm} mm")
        print("")
        print(f"  pickup base location:   {pickup_base}")
        print(f"  pickup shifted location:{pickup_plate.location}")
        print(f"  drop base location:     {drop_base}")
        print(f"  drop shifted location:  {drop_site.location}")
        print(f"  drop_site type:         {type(drop_site)}")
        print("")

        if args.mode == "deck":
            print("Mode deck: assignment/coordinate print only. No movement.")
            return

        if args.confirm != "RUN_ISWAP_PLATE_TEST":
            raise RuntimeError(
                "Refusing to move. Re-run with: --confirm RUN_ISWAP_PLATE_TEST"
            )

        print("MOVING PLATE with iSWAP: rail35 pos0 -> rail27 pos1 adjusted site...")
        print("Use EMPTY sacrificial plate. Destination slot must be physically empty. Hand near E-stop.")

        async with lh.backend.slow_iswap():
            await lh.move_resource(pickup_plate, drop_site)

        print("SUCCESS: iSWAP plate move command completed.")

    finally:
        print("Parking / stopping...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
