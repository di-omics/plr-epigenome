import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.standard import Mix
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

PLATE_RAIL = 26
PLATE_POS = 0
TROUGH_POS = 2

TRANSFER_VOL = 100

# trough pos 3 -> A4
SOURCE_WELL = "A4"

ASP_HEIGHT = [1.5] * 8
DSP_HEIGHT = [2.0] * 8
MIX_HEIGHT = [1.0] * 8

ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
DSP_OFFSETS = [Coordinate(-0.5, 2.75, 0.0)] * 8


async def add_from_trough(lh, source, targets, col_num):
    vols = [TRANSFER_VOL] * 8
    print(f"Adding 100 uL from trough {SOURCE_WELL} to plate column {col_num}...")
    await lh.aspirate(
        [source] * 8,
        vols=vols,
        liquid_height=ASP_HEIGHT,
        offsets=ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )
    await lh.dispense(
        targets,
        vols=vols,
        liquid_height=DSP_HEIGHT,
        offsets=DSP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )


async def transfer_plate_to_plate(lh, src, dst, src_num, dst_num):
    vols = [TRANSFER_VOL] * 8
    print(f"Transferring 100 uL from plate column {src_num} to plate column {dst_num} and mixing...")
    await lh.aspirate(
        src,
        vols=vols,
        liquid_height=DSP_HEIGHT,
        offsets=DSP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )
    await lh.dispense(
        dst,
        vols=vols,
        liquid_height=MIX_HEIGHT,
        offsets=DSP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
        mix=[Mix(volume=100, repetitions=5, flow_rate=100)] * 8,
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

    tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
    plate = CellTreat_96_wellplate_350ul_Fb(name="serial_dilution_plate")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="source_trough")

    tip_carrier[TIP_POS] = tips
    plate_carrier[PLATE_POS] = plate
    plate_carrier[TROUGH_POS] = trough

    source = trough[SOURCE_WELL][0]

    print("Picking up p1000 tips...")
    await lh.pick_up_tips(tips["A1:H1"])

    # preload columns 1-10 with 100 uL each
    for col in range(1, 11):
        await add_from_trough(lh, source, plate[f"A{col}:H{col}"], col)

    # extra 100 uL into column 1
    await add_from_trough(lh, source, plate["A1:H1"], 1)

    # serial dilute across 1 -> 10, mixing destination each step
    for col in range(1, 10):
        src = plate[f"A{col}:H{col}"]
        dst = plate[f"A{col+1}:H{col+1}"]
        await transfer_plate_to_plate(lh, src, dst, col, col + 1)

    print("Returning p1000 tips...")
    await lh.return_tips()

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())
