from pathlib import Path as _MethodPath
import sys as _method_sys

_METHOD_ROOT = next(
    parent for parent in _MethodPath(__file__).resolve().parents
    if parent.name == "hamilton-star"
)
if str(_METHOD_ROOT) not in _method_sys.path:
    _method_sys.path.insert(0, str(_METHOD_ROOT))
from operator_parameters import required_nonnegative, required_positive

import argparse
import asyncio
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# -----------------------------------------------------------------------------
# P10 ONLY refine script - WGS preparation new deck
#
# Purpose:
# - Isolate the FIRST p10 source 96DW -> work 96WP movement set.
# - Return tips to rack for dry/dev observation.
# - Do not run p50, p300, cleanup, iSWAP, autoload, or removals.
#
# Active layout:
# - Rail 48 pos0 = p10 filter tips
# - Rail 35 pos0 = work 96WP
# - Rail 35 pos2 = 96DW source plate
#
# Geometry changes requested after p10 source edge contact:
# - source aspirate Y increased substantially to clear edge
# - source effective Z raised back up for safety
# - destination Y slightly increased, destination height kept moderate
# -----------------------------------------------------------------------------

TIP_RAIL = 48
P10_TIP_POS = 0

LABWARE_RAIL = 35
WORK_96WP_POS = 0
SOURCE_96DW_POS = 2

# P10 source -> work refine geometry.
# Prior HEIGHT_ONLY baseline:
#   P10_96DW_ASP_HEIGHT = 15.0
#   P10_96DW_ASP_OFFSETS = Coordinate(0.20, 2.30, 0.0)
#   SAFE_96WP_DSP_HEIGHT = 20.0
#   SAFE_96WP_DSP_OFFSETS = Coordinate(0.35, 2.45, 0.0)
#
# This refine pass:
P10_96DW_ASP_HEIGHT = [13.0] * 8
P10_96DW_ASP_OFFSETS = [Coordinate(0.20, 4.40, 0.0)] * 8

P10_WORK_DSP_HEIGHT = [16.0] * 8
P10_WORK_DSP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8

P10_BLOWOUT_AIR_VOLUME = 0.8

# p10 first-set WGS preparation additions only.
# These are dry/dev movements in this file; tips are returned.
P10_SOURCE_STEPS = [
    (1, required_positive("wgs.stage_1_volume_ul"), "operator WGS stage 1"),
    (2, required_positive("wgs.stage_2_volume_ul"), "operator WGS stage 2"),
    (3, required_positive("wgs.stage_3_volume_ul"), "operator WGS stage 3"),
    (4, required_positive("wgs.stage_4_volume_ul"), "operator WGS stage 4"),
    (5, required_positive("wgs.stage_5_volume_ul"), "operator WGS stage 5"),
    (6, required_positive("wgs.stage_6_volume_ul"), "operator WGS stage 6"),
]

P10_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_10uL_filter",
    "hamilton_96_tiprack_10ul_filter",
]

SOURCE_96DW_CANDIDATES = [
    "nest_96_wellplate_2mL_deep",
    "nest_96_wellplate_2mL_Vb",
    "Cor_96_wellplate_2mL_Vb",
    "Cor_96_wellplate_2mL_Ub",
    "Greiner_96_wellplate_2mL_Vb",
    "Axygen_96_wellplate_2mL_Vb",
]


def make_resource_from_candidates(label: str, name: str, candidates: List[str], nearby_terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)

    terms = [term.lower() for term in nearby_terms]
    available = sorted(
        n for n in dir(plr_resources)
        if any(term in n.lower() for term in terms)
    )
    raise RuntimeError(
        f"Could not find a PyLabRobot resource factory for {label}. "
        f"Tried: {candidates}. Nearby installed names: {available[:160]}"
    )


def make_p10_tiprack(name: str):
    return make_resource_from_candidates(
        "p10 filter tips",
        name,
        P10_TIP_FACTORY_CANDIDATES,
        nearby_terms=["tip", "10", "htf"],
    )


def make_96dw_source_plate(name: str):
    return make_resource_from_candidates(
        "96DW source plate",
        name,
        SOURCE_96DW_CANDIDATES,
        nearby_terms=["96", "deep", "2ml", "wellplate"],
    )


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


def parse_cols(s: str) -> List[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning p10 refine deck resources...")

    tip_carrier_48 = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")

    lh.deck.assign_child_resource(tip_carrier_48, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tiprack(name="r48_p10_filter_tips")
    source_96dw = make_96dw_source_plate(name="rail35_pos2_source_96dw")
    work_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_work_96wp")

    tip_carrier_48[P10_TIP_POS] = p10_tips
    labware_carrier[WORK_96WP_POS] = work_96wp
    labware_carrier[SOURCE_96DW_POS] = source_96dw

    print("\nAssigned resources:")
    print(f"tip_carrier_48: {tip_carrier_48.location}")
    print(f"labware_carrier: {labware_carrier.location}")
    print(f"p10_tips: {p10_tips.location}")
    print(f"source_96dw: {source_96dw.location}")
    print(f"work_96wp: {work_96wp.location}")

    print("\nP10 refine geometry:")
    print(f"P10_96DW_ASP_HEIGHT = {P10_96DW_ASP_HEIGHT}")
    print(f"P10_96DW_ASP_OFFSETS = {P10_96DW_ASP_OFFSETS}")
    print(f"P10_WORK_DSP_HEIGHT = {P10_WORK_DSP_HEIGHT}")
    print(f"P10_WORK_DSP_OFFSETS = {P10_WORK_DSP_OFFSETS}")

    return {
        "p10_tips": p10_tips,
        "source_96dw": source_96dw,
        "work_96wp": work_96wp,
    }


async def transfer_column_p10(lh: LiquidHandler, source_wells, target_wells, vol: float, label: str):
    vols = [vol] * 8

    print(f"Aspirating {vol} uL from {label}...")
    await lh.aspirate(
        source_wells,
        vols=vols,
        liquid_height=P10_96DW_ASP_HEIGHT,
        offsets=P10_96DW_ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL to work 96WP column at refined p10 dispense geometry...")
    await lh.dispense(
        target_wells,
        vols=vols,
        liquid_height=P10_WORK_DSP_HEIGHT,
        offsets=P10_WORK_DSP_OFFSETS,
        blow_out_air_volume=[P10_BLOWOUT_AIR_VOLUME] * 8,
    )


async def run_p10_refine(lh: LiquidHandler, resources: Dict[str, object], source_cols: List[int], dest_col: int):
    p10_tips = resources["p10_tips"]
    source_96dw = resources["source_96dw"]
    work_96wp = resources["work_96wp"]

    selected_steps = [step for step in P10_SOURCE_STEPS if step[0] in source_cols]
    if not selected_steps:
        raise RuntimeError(f"No p10 source steps selected for source_cols={source_cols}")

    print("\n=== P10 REFINE ONLY: rail35 pos2 source 96DW -> rail35 pos0 work 96WP ===")
    print(f"Selected source columns: {source_cols}; destination column: {dest_col}")
    print("Dry/dev behavior: tips are returned to rail48 pos0 when done.")

    await lh.pick_up_tips(p10_tips["A1:H1"])

    try:
        for src_col, vol, label in selected_steps:
            await transfer_column_p10(
                lh,
                source_96dw[f"A{src_col}:H{src_col}"],
                wells_for_column(work_96wp, dest_col),
                vol,
                f"source 96DW column {src_col} ({label})",
            )
    finally:
        print("Returning p10 tips to rack for dry/dev run...")
        await lh.return_tips()

    print("SUCCESS: p10 refine movement set completed.")


async def main():
    parser = argparse.ArgumentParser(description="P10-only source-to-work geometry refine script.")
    parser.add_argument(
        "--mode",
        choices=["deck", "p10-refine"],
        default="deck",
        help="Use deck first, then p10-refine.",
    )
    parser.add_argument(
        "--source-cols",
        default="1,2,3,4,5,6",
        help="Comma-separated 96DW source columns to test. Default: 1,2,3,4,5,6.",
    )
    parser.add_argument(
        "--dest-col",
        type=int,
        default=1,
        help="Work plate destination column. Default: 1.",
    )
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        resources = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No tip pickup or liquid handling executed.")
        elif args.mode == "p10-refine":
            await run_p10_refine(
                lh,
                resources,
                source_cols=parse_cols(args.source_cols),
                dest_col=args.dest_col,
            )

    finally:
        print("Stopping STAR backend...")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
