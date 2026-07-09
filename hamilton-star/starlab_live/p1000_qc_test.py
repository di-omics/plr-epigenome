import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    hamilton_96_tiprack_1000uL_filter,
    hamilton_96_tiprack_300uL_filter,
    hamilton_96_tiprack_50uL_filter,
    Coordinate,
)

TIP_RAIL = 19
P1000_TIP_POS = 0
P300_TIP_POS = 1
P50_TIP_POS = 2

PLATE_RAIL = 26
PLATE_POS = 0
TROUGH_POS = 2

P1000_VOL = 200
P300_VOL = 200
P50_VOL = 50

ASP_LIQUID_HEIGHT = [1.5] * 8
DSP_LIQUID_HEIGHT = [2.5] * 8

ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
DSP_OFFSETS = [Coordinate(-0.5, 2.75, 0.0)] * 8


async def dispense_column(lh, source, targets, volumes, col_num, label):
    print(f"Aspirating from trough {label} for plate column {col_num}...")
    await lh.aspirate(
        [source] * 8,
        vols=volumes,
        liquid_height=ASP_LIQUID_HEIGHT,
        offsets=ASP_OFFSETS,
    )

    print(f"Dispensing into plate column {col_num}...")
    await lh.dispense(
        targets,
        vols=volumes,
        liquid_height=DSP_LIQUID_HEIGHT,
        offsets=DSP_OFFSETS,
    )


async def main():
    print("Initializing STAR...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    print("Assigning deck resources...")

    tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

    plate_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{PLATE_RAIL}")
    lh.deck.assign_child_resource(plate_carrier, rails=PLATE_RAIL)

    p1000_tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
    p300_tips = hamilton_96_tiprack_300uL_filter(name="p300_filter_tips")
    p50_tips = hamilton_96_tiprack_50uL_filter(name="p50_filter_tips")

    plate = CellTreat_96_wellplate_350ul_Fb(name="qc_plate")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="water_trough")

    tip_carrier[P1000_TIP_POS] = p1000_tips
    tip_carrier[P300_TIP_POS] = p300_tips
    tip_carrier[P50_TIP_POS] = p50_tips

    plate_carrier[PLATE_POS] = plate
    plate_carrier[TROUGH_POS] = trough

    source_a1 = trough["A1"][0]
    source_a2 = trough["A2"][0]

    # p1000 block: columns 1-4, 200 uL from trough A1
    print("Picking up p1000 tips...")
    await lh.pick_up_tips(p1000_tips["A1:H1"])
    p1000_volumes = [P1000_VOL] * 8

    await dispense_column(lh, source_a1, plate["A1:H1"], p1000_volumes, 1, "A1")
    await dispense_column(lh, source_a1, plate["A2:H2"], p1000_volumes, 2, "A1")
    await dispense_column(lh, source_a1, plate["A3:H3"], p1000_volumes, 3, "A1")
    await dispense_column(lh, source_a1, plate["A4:H4"], p1000_volumes, 4, "A1")

    print("Returning p1000 tips...")
    await lh.return_tips()

    # p300 block: columns 5-8, 200 uL from trough A2
    print("Picking up p300 tips...")
    await lh.pick_up_tips(p300_tips["A1:H1"])
    p300_volumes = [P300_VOL] * 8

    await dispense_column(lh, source_a2, plate["A5:H5"], p300_volumes, 5, "A2")
    await dispense_column(lh, source_a2, plate["A6:H6"], p300_volumes, 6, "A2")
    await dispense_column(lh, source_a2, plate["A7:H7"], p300_volumes, 7, "A2")
    await dispense_column(lh, source_a2, plate["A8:H8"], p300_volumes, 8, "A2")

    print("Returning p300 tips...")
    await lh.return_tips()

    # p50 block: columns 9-12, 50 uL from trough A2
    print("Picking up p50 tips...")
    await lh.pick_up_tips(p50_tips["A1:H1"])
    p50_volumes = [P50_VOL] * 8

    await dispense_column(lh, source_a2, plate["A9:H9"], p50_volumes, 9, "A2")
    await dispense_column(lh, source_a2, plate["A10:H10"], p50_volumes, 10, "A2")
    await dispense_column(lh, source_a2, plate["A11:H11"], p50_volumes, 11, "A2")
    await dispense_column(lh, source_a2, plate["A12:H12"], p50_volumes, 12, "A2")

    print("Returning p50 tips...")
    await lh.return_tips()

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())
