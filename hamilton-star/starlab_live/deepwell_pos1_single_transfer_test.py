import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    AGenBio_96_wellplate_Ub_2200ul,
    hamilton_96_tiprack_1000uL_filter,
    Coordinate,
)

TIP_RAIL = 19
TIP_POS = 0

PLATE_RAIL = 26
DEEPWELL_POS = 1
TROUGH_POS = 2

ASP_HEIGHT = [1.5] * 8
DSP_HEIGHT = [3.0] * 8

ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
DSP_OFFSETS = [Coordinate(0.55, 0.2, 1.0)] * 8


async def main():
    print("Initializing STAR...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    print("Assigning deck resources...")
    tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

    plate_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{PLATE_RAIL}")
    lh.deck.assign_child_resource(plate_carrier, rails=PLATE_RAIL)

    tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
    deepwell = AGenBio_96_wellplate_Ub_2200ul(name="deepwell_plate")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="water_trough")

    tip_carrier[TIP_POS] = tips
    plate_carrier[DEEPWELL_POS] = deepwell
    plate_carrier[TROUGH_POS] = trough

    source = trough["A1"][0]      # trough well A1
    targets = deepwell["A2:H2"]   # deepwell column 2
    volumes = [200] * 8

    print("Picking up p1000 tips...")
    await lh.pick_up_tips(tips["A1:H1"])

    print("Aspirating 200 uL from trough A1...")
    await lh.aspirate(
        [source] * 8,
        vols=volumes,
        liquid_height=ASP_HEIGHT,
        offsets=ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print("Dispensing 200 uL into deepwell plate column 2 with adjusted offset...")
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
