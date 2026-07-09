import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    hamilton_96_tiprack_1000uL_filter,
    hamilton_96_tiprack_50uL_filter,
    Coordinate,
)

TIP_RAIL = 19
P1000_TIP_POS = 0
P50_TIP_POS = 1

PLATE_RAIL = 26
PLATE_POS = 0
TROUGH_POS = 2

P1000_ASP_HEIGHT = [1.5] * 8
P1000_DSP_HEIGHT = [2.0] * 8

P50_ASP_HEIGHT = [1.5] * 8
P50_DSP_HEIGHT = [2.0] * 8

P1000_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P1000_DSP_OFFSETS = [Coordinate(-0.5, 2.75, 0.0)] * 8

P50_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P50_DSP_OFFSETS = [Coordinate(-0.5, 2.75, 0.0)] * 8


async def transfer_column(lh, source, targets, vol, col_num, asp_height, dsp_height, asp_offsets, dsp_offsets, source_label):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL from trough {source_label} for plate column {col_num}...")
    await lh.aspirate(
        [source] * 8,
        vols=volumes,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL into plate column {col_num}...")
    await lh.dispense(
        targets,
        vols=volumes,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[0.0] * 8,
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
    p50_tips = hamilton_96_tiprack_50uL_filter(name="p50_filter_tips")
    plate = CellTreat_96_wellplate_350ul_Fb(name="qc_plate")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="water_trough")

    tip_carrier[P1000_TIP_POS] = p1000_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    plate_carrier[PLATE_POS] = plate
    plate_carrier[TROUGH_POS] = trough

    source_p1000 = trough["A1"][0]  # trough pos 0
    source_p50 = trough["A2"][0]    # trough pos 1

    # p1000 block
    print("Picking up p1000 tips from tip pos 0...")
    await lh.pick_up_tips(p1000_tips["A1:H1"])

    for col in [1, 2, 3]:
        await transfer_column(
            lh, source_p1000, plate[f"A{col}:H{col}"], 200, col,
            P1000_ASP_HEIGHT, P1000_DSP_HEIGHT, P1000_ASP_OFFSETS, P1000_DSP_OFFSETS, "A1"
        )

    for col in [4, 5, 6]:
        await transfer_column(
            lh, source_p1000, plate[f"A{col}:H{col}"], 100, col,
            P1000_ASP_HEIGHT, P1000_DSP_HEIGHT, P1000_ASP_OFFSETS, P1000_DSP_OFFSETS, "A1"
        )

    print("Returning p1000 tips...")
    await lh.return_tips()

    # p50 block
    print("Picking up p50 tips from tip pos 1...")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    for col in [7, 8, 9]:
        await transfer_column(
            lh, source_p50, plate[f"A{col}:H{col}"], 50, col,
            P50_ASP_HEIGHT, P50_DSP_HEIGHT, P50_ASP_OFFSETS, P50_DSP_OFFSETS, "A2"
        )

    for col in [10, 11, 12]:
        await transfer_column(
            lh, source_p50, plate[f"A{col}:H{col}"], 25, col,
            P50_ASP_HEIGHT, P50_DSP_HEIGHT, P50_ASP_OFFSETS, P50_DSP_OFFSETS, "A2"
        )

    print("Returning p50 tips...")
    await lh.return_tips()

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())
