import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    hamilton_96_tiprack_1000uL_filter,
    Coordinate,
)

TIP_RAIL = 19
TIP_POS = 0

SOURCE_RAIL = 26
TROUGH_POS = 2

DEST_RAIL = 33
DEST_POS = 0

P1000_ASP_HEIGHT = [1.5] * 8
P1000_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P1000_DSP_HEIGHT = [5.0] * 8
P1000_DSP_OFFSETS = [Coordinate(0.10, 2.45, 30.0)] * 8


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

    tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="water_trough")
    dest_plate = CellTreat_96_wellplate_350ul_Fb(name="dest_96wp")

    tip_carrier[TIP_POS] = tips
    source_carrier[TROUGH_POS] = trough
    dest_carrier[DEST_POS] = dest_plate

    source = trough["A1"][0]
    targets = dest_plate["A1:H1"]
    volumes = [200] * 8

    print("Picking up p1000 tips...")
    await lh.pick_up_tips(tips["A1:H1"])

    print("Aspirating 200 uL from trough A1...")
    await lh.aspirate(
        [source] * 8,
        vols=volumes,
        liquid_height=P1000_ASP_HEIGHT,
        offsets=P1000_ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print("Dispensing 200 uL into elevated 96WP column 1...")
    await lh.dispense(
        targets,
        vols=volumes,
        liquid_height=P1000_DSP_HEIGHT,
        offsets=P1000_DSP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print("Returning tips...")
    await lh.return_tips()

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())
