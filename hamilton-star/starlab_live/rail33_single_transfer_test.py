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
P1000_TIP_POS = 0

PLATE_RAIL = 33
PLATE_POS = 0

TROUGH_RAIL = 26
TROUGH_POS = 2

ASP_HEIGHT = [1.5] * 8
DSP_HEIGHT = [2.0] * 8

ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
DSP_OFFSETS = [Coordinate(-0.5, 2.75, 22.9)] * 8


async def main():
    print("Initializing STAR...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    print("Assigning deck resources...")
    tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

    plate_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{PLATE_RAIL}")
    lh.deck.assign_child_resource(plate_carrier, rails=PLATE_RAIL)

    trough_carrier = PLT_CAR_L5AC_A00(name=f"trough_car_rail{TROUGH_RAIL}")
    lh.deck.assign_child_resource(trough_carrier, rails=TROUGH_RAIL)

    p1000_tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
    plate = CellTreat_96_wellplate_350ul_Fb(name="qc_plate")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="water_trough")

    tip_carrier[P1000_TIP_POS] = p1000_tips
    plate_carrier[PLATE_POS] = plate
    trough_carrier[TROUGH_POS] = trough

    source = trough["A1"][0]
    targets = plate["A1:H1"]
    volumes = [200] * 8

    print("Picking up p1000 tips...")
    await lh.pick_up_tips(p1000_tips["A1:H1"])

    print("Aspirating 200 uL from trough A1...")
    await lh.aspirate(
        [source] * 8,
        vols=volumes,
        liquid_height=ASP_HEIGHT,
        offsets=ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print("Dispensing 200 uL into elevated plate column 1...")
    await lh.dispense(
        targets,
        vols=volumes,
        liquid_height=DSP_HEIGHT,
        offsets=DSP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print("Returning tips...")
    await lh.return_tips()

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())
