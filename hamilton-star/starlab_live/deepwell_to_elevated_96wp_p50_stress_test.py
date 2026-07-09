import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    AGenBio_96_wellplate_Ub_2200ul,
    CellTreat_96_wellplate_350ul_Fb,
    hamilton_96_tiprack_50uL_filter,
    Coordinate,
)

TIP_RAIL = 19
P50_TIP_POS = 1

SOURCE_RAIL = 26
SOURCE_POS = 1

DEST_RAIL = 33
DEST_POS = 0

P50_ASP_HEIGHT = [4.5] * 8
P50_ASP_OFFSETS = [Coordinate(0.20, 2.30, 0.5)] * 8

P50_DSP_HEIGHT = [5.0] * 8
P50_DSP_OFFSETS = [Coordinate(0.10, 2.45, 27.0)] * 8


async def transfer_column(lh, source_wells, target_wells, vol, col_num):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL from deepwell column {col_num}...")
    await lh.aspirate(
        source_wells,
        vols=volumes,
        liquid_height=P50_ASP_HEIGHT,
        offsets=P50_ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL into elevated 96WP column {col_num}...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=P50_DSP_HEIGHT,
        offsets=P50_DSP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )


async def main():
    print("Initializing STAR...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    print("Assigning deck resources...")
    tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

    source_carrier = PLT_CAR_L5AC_A00(name=f"source_car_rail{SOURCE_RAIL}")
    lh.deck.assign_child_resource(source_carrier, rails=SOURCE_RAIL)

    dest_carrier = PLT_CAR_L5AC_A00(name=f"dest_car_rail{DEST_RAIL}")
    lh.deck.assign_child_resource(dest_carrier, rails=DEST_RAIL)

    p50_tips = hamilton_96_tiprack_50uL_filter(name="p50_filter_tips")
    source_plate = AGenBio_96_wellplate_Ub_2200ul(name="source_deepwell")
    dest_plate = CellTreat_96_wellplate_350ul_Fb(name="dest_96wp")

    tip_carrier[P50_TIP_POS] = p50_tips
    source_carrier[SOURCE_POS] = source_plate
    dest_carrier[DEST_POS] = dest_plate

    print("Picking up p50 tips...")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    for col in [1, 2, 3, 4, 5, 6]:
        await transfer_column(
            lh,
            source_plate[f"A{col}:H{col}"],
            dest_plate[f"A{col}:H{col}"],
            50,
            col,
        )

    for col in [7, 8, 9, 10, 11, 12]:
        await transfer_column(
            lh,
            source_plate[f"A{col}:H{col}"],
            dest_plate[f"A{col}:H{col}"],
            25,
            col,
        )

    print("Returning p50 tips...")
    await lh.return_tips()

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())
