import argparse
import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources import Coordinate
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import PLT_CAR_L5AC_A00
from pylabrobot.resources import Cor_96_wellplate_360ul_Fb


HHS_RAIL = 27
HHS_POSITION = 2

RETURN_RAIL = 35
RETURN_POSITION = 0


def shifted(coord, dx=0.0, dy=0.0, dz=0.0):
    return Coordinate(coord.x + dx, coord.y + dy, coord.z + dz)


async def main():
    parser = argparse.ArgumentParser(
        description="iSWAP return test: HHS rail27 pos2 -> rail35 pos0."
    )
    parser.add_argument("--hhs-pickup-x-offset-mm", type=float, default=14.0)
    parser.add_argument("--hhs-pickup-y-offset-mm", type=float, default=47.5)
    parser.add_argument("--hhs-pickup-z-offset-mm", type=float, default=10.0)
    parser.add_argument("--return-drop-z-offset-mm", type=float, default=8.5)
    args = parser.parse_args()

    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    try:
        print("Initializing STAR with skip_autoload=True...")
        await lh.setup(skip_autoload=True)

        print("Assigning HHS pickup carrier rail27 and return carrier rail35...")
        hhs_carrier = PLT_CAR_L5AC_A00(name="hhs_pickup_carrier_rail27")
        return_carrier = PLT_CAR_L5AC_A00(name="return_carrier_rail35")

        lh.deck.assign_child_resource(hhs_carrier, rails=HHS_RAIL)
        lh.deck.assign_child_resource(return_carrier, rails=RETURN_RAIL)

        plate = Cor_96_wellplate_360ul_Fb(name="iswap_plate_on_hhs_rail27_pos2")
        hhs_carrier[HHS_POSITION] = plate

        hhs_base = plate.location
        plate.location = shifted(
            hhs_base,
            dx=args.hhs_pickup_x_offset_mm,
            dy=args.hhs_pickup_y_offset_mm,
            dz=args.hhs_pickup_z_offset_mm,
        )

        drop_site = return_carrier[RETURN_POSITION]
        drop_base = drop_site.location
        drop_site.location = shifted(
            drop_base,
            dz=args.return_drop_z_offset_mm,
        )

        print("")
        print("iSWAP RETURN TEST: HHS rail27 pos2 -> rail35 pos0")
        print("Physical requirements:")
        print("  plate is currently on HHS rail27 pos2")
        print("  rail35 pos0 is empty")
        print("  hand near E-stop")
        print("")
        print(f"  HHS pickup base:      {hhs_base}")
        print(f"  HHS pickup shifted:   {plate.location}")
        print(f"  return drop base:     {drop_base}")
        print(f"  return drop shifted:  {drop_site.location}")
        print("")
        print("MOVING PLATE...")
        await lh.move_resource(plate, drop_site)
        print("SUCCESS: iSWAP returned plate from HHS rail27 pos2 to rail35 pos0.")

    finally:
        print("Stopping STAR backend...")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
