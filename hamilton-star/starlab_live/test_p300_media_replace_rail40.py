import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources


TIP_RAIL = 19
P300_TIP_POS = 2

SOURCE_RAIL = 26
TROUGH_POS = 2

PLATE_RAIL = 40
PLATE_POS = 0

SOURCE_WELL = "A4"   # media / water / dye source
WASTE_WELL = "A12"   # waste/test waste in trough
DEST_COL = 1

VOL_MEDIA = 100  # uL

DISPENSE_BLOWOUT_AIR_VOLUME = 5.0

# Working physical tip definition for Hamilton 300 uL CO-RE II filtered tips.
P300_TIPRACK_FACTORY = "hamilton_96_tiprack_300uL_filter_slim"

# Trough/source geometry.
P300_TROUGH_ASP_HEIGHT = [0.0] * 8
P300_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, -24.0)] * 8

P300_WASTE_DSP_HEIGHT = [0.0] * 8
P300_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, -24.0)] * 8

# Rail 40 / cleanup plate geometry.
# Start with the same XY/Z style that worked for rail 40 cleanup additions.
P300_PLATE_DSP_HEIGHT = [0.0] * 8
P300_PLATE_DSP_OFFSETS = [Coordinate(-0.60, 1.55, -12.0)] * 8

# Removal geometry. This is the part we are validating.
# Keep it conservative initially; tune lower if removal is incomplete.
P300_PLATE_ASP_HEIGHT = [0.0] * 8
P300_PLATE_ASP_OFFSETS = [Coordinate(-0.60, 1.55, -8.0)] * 8


def make_p300_filter_slim_tiprack(name: str):
    factory = getattr(plr_resources, P300_TIPRACK_FACTORY, None)
    if factory is None:
        raise RuntimeError(f"Missing PLR resource factory: {P300_TIPRACK_FACTORY}")
    print(f"Using p300 tiprack resource factory: {P300_TIPRACK_FACTORY}")
    return factory(name=name)


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]

def shifted_coordinate(loc, dz: float):
    return Coordinate(loc.x, loc.y, loc.z + dz)



async def main():
    print("Initializing STAR for p300 media add/remove test...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning deck resources...")

        tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
        source_carrier = PLT_CAR_L5AC_A00(name=f"source_car_rail{SOURCE_RAIL}")
        plate_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{PLATE_RAIL}")

        lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
        lh.deck.assign_child_resource(source_carrier, rails=SOURCE_RAIL)
        lh.deck.assign_child_resource(plate_carrier, rails=PLATE_RAIL)

        p300_tips = make_p300_filter_slim_tiprack(name="p300_filter_slim_tips")
        trough = CellTreat_12_troughplate_15000ul_Vb(name="media_trough")
        plate = CellTreat_96_wellplate_350ul_Fb(name="rail40_test_plate")

        tip_carrier[P300_TIP_POS] = p300_tips
        source_carrier[TROUGH_POS] = trough
        plate_carrier[PLATE_POS] = plate

        source = trough[SOURCE_WELL][0]
        waste = trough[WASTE_WELL][0]
        targets = wells_for_column(plate, DEST_COL)
        vols = [VOL_MEDIA] * 8

        print(f"Picking up p300 filter slim tips from rail {TIP_RAIL} pos {P300_TIP_POS} A1:H1...")
        await lh.pick_up_tips(p300_tips["A1:H1"])

        print(f"ADDING {VOL_MEDIA} uL from trough {SOURCE_WELL} -> rail {PLATE_RAIL} col {DEST_COL}...")
        await lh.aspirate(
            [source] * 8,
            vols=vols,
            liquid_height=P300_TROUGH_ASP_HEIGHT,
            offsets=P300_TROUGH_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        await lh.dispense(
            targets,
            vols=vols,
            liquid_height=P300_PLATE_DSP_HEIGHT,
            offsets=P300_PLATE_DSP_OFFSETS,
            blow_out_air_volume=[DISPENSE_BLOWOUT_AIR_VOLUME] * 8,
        )

        print(f"REMOVING {VOL_MEDIA} uL from rail {PLATE_RAIL} col {DEST_COL} -> trough {WASTE_WELL}...")

        # DIAGNOSTIC: aspirate offsets did not appear to change physical Z.
        # Temporarily lower the plate resource itself for the aspirate move.
        original_plate_location = Coordinate(plate.location.x, plate.location.y, plate.location.z)
        plate.location = shifted_coordinate(plate.location, dz=-20.0)
        print(f"Temporarily shifted plate resource down for aspirate: {plate.location}")

        await lh.aspirate(
            targets,
            vols=vols,
            liquid_height=P300_PLATE_ASP_HEIGHT,
            offsets=P300_PLATE_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )

        plate.location = original_plate_location
        print(f"Restored plate resource location after aspirate: {plate.location}")
        await lh.dispense(
            [waste] * 8,
            vols=vols,
            liquid_height=P300_WASTE_DSP_HEIGHT,
            offsets=P300_WASTE_DSP_OFFSETS,
            blow_out_air_volume=[DISPENSE_BLOWOUT_AIR_VOLUME] * 8,
        )

        print("Returning p300 tips for dev test...")
        await lh.return_tips()

        print("SUCCESS: p300 media add/remove test completed.")

    finally:
        print("Stopping...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
