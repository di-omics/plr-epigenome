import asyncio
from pathlib import Path as _MethodPath
import sys as _method_sys

_METHOD_ROOT = next(
    parent for parent in _MethodPath(__file__).resolve().parents
    if parent.name == "hamilton-star"
)
if str(_METHOD_ROOT) not in _method_sys.path:
    _method_sys.path.insert(0, str(_METHOD_ROOT))
from operator_parameters import required_positive

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    CellTreat_96_wellplate_350ul_Ub,
    hamilton_96_tiprack_1000uL_filter,
    hamilton_96_tiprack_50uL_filter,
    Coordinate,
)

TIP_RAIL = 19
P1000_TIP_POS = 0
P50_TIP_POS = 1

SOURCE_RAIL = 26
SOURCE_POS = 1
TROUGH_POS = 2

DEST_RAIL = 33
DEST_POS = 0

P50_ASP_HEIGHT = [4.5] * 8
P50_ASP_OFFSETS = [Coordinate(0.20, 2.30, 0.5)] * 8

P50_DSP_HEIGHT = [5.0] * 8
P50_DSP_OFFSETS = [Coordinate(0.10, 2.45, 27.0)] * 8

P1000_ASP_HEIGHT = [1.5] * 8
P1000_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P1000_DSP_HEIGHT = [5.0] * 8
P1000_DSP_OFFSETS = [Coordinate(0.10, 2.20, 30.0)] * 8


async def transfer_column(
    lh,
    source_wells,
    target_wells,
    vol,
    asp_height,
    dsp_height,
    asp_offsets,
    dsp_offsets,
    label,
):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL from {label}...")
    await lh.aspirate(
        source_wells,
        vols=volumes,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL into destination column...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )


async def transfer_from_trough(
    lh,
    source_well,
    target_wells,
    vol,
    asp_height,
    dsp_height,
    asp_offsets,
    dsp_offsets,
    label,
):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL from trough {label}...")
    await lh.aspirate(
        [source_well] * 8,
        vols=volumes,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL into destination column...")
    await lh.dispense(
        target_wells,
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

    source_carrier = PLT_CAR_L5AC_A00(name=f"source_car_rail{SOURCE_RAIL}")
    lh.deck.assign_child_resource(source_carrier, rails=SOURCE_RAIL)

    dest_carrier = PLT_CAR_L5AC_A00(name=f"dest_car_rail{DEST_RAIL}")
    lh.deck.assign_child_resource(dest_carrier, rails=DEST_RAIL)

    p1000_tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
    p50_tips = hamilton_96_tiprack_50uL_filter(name="p50_filter_tips")

    source_plate = CellTreat_96_wellplate_350ul_Ub(name="source_reagent_plate")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="bulk_liquid_trough")
    dest_plate = CellTreat_96_wellplate_350ul_Fb(name="dest_96wp")

    tip_carrier[P1000_TIP_POS] = p1000_tips
    tip_carrier[P50_TIP_POS] = p50_tips

    source_carrier[SOURCE_POS] = source_plate
    source_carrier[TROUGH_POS] = trough
    dest_carrier[DEST_POS] = dest_plate

    dest_targets = dest_plate["A1:H1"]

    reagent1 = source_plate["A1:H1"]
    reagent2 = source_plate["A2:H2"]
    bulk1 = trough["A1"][0]

    print("Picking up p50 tips...")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    await transfer_column(
        lh,
        reagent1,
        dest_targets,
        required_positive("wgs.stage_1_volume_ul"),
        P50_ASP_HEIGHT,
        P50_DSP_HEIGHT,
        P50_ASP_OFFSETS,
        P50_DSP_OFFSETS,
        "source plate column 1",
    )

    await transfer_column(
        lh,
        reagent2,
        dest_targets,
        required_positive("wgs.stage_2_volume_ul"),
        P50_ASP_HEIGHT,
        P50_DSP_HEIGHT,
        P50_ASP_OFFSETS,
        P50_DSP_OFFSETS,
        "source plate column 2",
    )

    print("Returning p50 tips...")
    await lh.return_tips()

    # Optional bulk proof-of-concept values must come from the approved local
    # method profile before that path is implemented.

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())
