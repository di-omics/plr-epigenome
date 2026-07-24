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
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# -----------------------------------------------------------------------------
# WGS preparation (WGS preparation) - p300 ethanol wash add/remove focused test
# Hamilton STAR + PyLabRobot on starpi
#
# Purpose:
# - Focused p300 development for post-amplification cleanup wash handling.
# - Tests reservoir/trough at rail35 pos3 -> plate on magnet/placeholder at rail35 pos1.
# - Tests removal from rail35 pos1 plate -> reservoir waste well at rail35 pos3.
# - Excludes p10/p50 source-to-work, p1000, iSWAP, and full protocol logic.
#
# Method context:
# - The local WGS profile supplies the wash liquid volume and incubation.
# - This file starts with bead-safe/high removal geometry for observation.
#
# Active deck:
# - Rail 48 pos2 = p300 filter slim tips
# - Rail 35 pos1 = 96WP on magnetic rack / mag placeholder
# - Rail 35 pos3 = 12-well reservoir/trough
#
# Testing behavior:
# - Tips return to rack by default.
# - For true wet/reagent testing, pass --discard-tips.
#
# Starting geometry:
# - Add aspirate from trough uses high-ish trough height.
# - Add dispense into mag plate uses p10/p50-relative work-plate side-wall style.
# - Removal aspirate from mag plate is conservative/high to avoid bead/bottom contact.
#   Tune downward only after visual validation.
# -----------------------------------------------------------------------------

TIP_RAIL = 48
P300_TIP_POS = 2

LABWARE_RAIL = 35
MAG_96WP_POS = 1
TROUGH_POS = 3

DEST_COLUMNS = [1]

# Trough source/waste wells in 12-well reservoir.
# A2/A3 map to ethanol 1/2 in prior WGS preparation scaffold. A12 is waste/sink for test removals.
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_WATER_TEST = "A5"
TROUGH_WASTE = "A12"

# Default test volumes.
DEFAULT_ADD_VOL = required_positive("wgs.cleanup.wash_add_ul")
# Removal intentionally starts below the full operator-profile wash addition to reduce risk while geometry is being tuned.
DEFAULT_REMOVE_VOL = required_positive("wgs.cleanup.wash_remove_ul")

# P300 add geometry: reservoir -> plate on mag/placeholder.
P300_TROUGH_ASP_HEIGHT = [15.0] * 8
P300_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

# Initial plate dispense geometry is relative to current p10/p50 side-wall dispense.
P300_MAG_DSP_HEIGHT = [16.0] * 8
P300_MAG_DSP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8

# P300 removal geometry: plate on mag/placeholder -> reservoir waste.
# Starts conservative/high. Lower height gradually after bead-safe visual checks.
P300_MAG_REMOVE_ASP_HEIGHT = [12.0] * 8
P300_MAG_REMOVE_ASP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8

# Waste dispense into reservoir should be safely above/broad.
P300_WASTE_DSP_HEIGHT = [25.0] * 8
P300_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P300_ADD_BLOWOUT_AIR_VOLUME = 3.0
P300_REMOVE_BLOWOUT_AIR_VOLUME = 2.0

P300_TIP_FACTORY_CANDIDATES = [
    # NEST 345112 300uL Filter Conductive tips: try standard/non-slim p300 first.
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
    "hamilton_96_tiprack_300uL_filter_slim",
    "hamilton_96_tiprack_300ul_filter_slim",
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


def make_p300_tiprack(name: str):
    return make_resource_from_candidates(
        "p300 filter slim tips",
        name,
        P300_TIP_FACTORY_CANDIDATES,
        nearby_terms=["tip", "300", "htf"],
    )


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


def tips_for_column(rack, col: int):
    return rack[f"A{col}:H{col}"]


def parse_cols(s: str) -> List[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning p300 ethanol add/remove deck resources...")

    tip_carrier_48 = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")

    lh.deck.assign_child_resource(tip_carrier_48, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p300_tips = make_p300_tiprack(name="r48_p300_filter_slim_tips")
    mag_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_mag_96wp_placeholder")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_12w_reservoir")

    tip_carrier_48[P300_TIP_POS] = p300_tips
    labware_carrier[MAG_96WP_POS] = mag_96wp
    labware_carrier[TROUGH_POS] = trough

    print("\nAssigned resources:")
    print(f"tip_carrier_48: {tip_carrier_48.location}")
    print(f"labware_carrier: {labware_carrier.location}")
    print(f"p300_tips: {p300_tips.location}")
    print(f"mag_96wp: {mag_96wp.location}")
    print(f"trough: {trough.location}")

    print("\nP300 add/remove geometry:")
    print(f"P300_TROUGH_ASP_HEIGHT = {P300_TROUGH_ASP_HEIGHT}")
    print(f"P300_TROUGH_ASP_OFFSETS = {P300_TROUGH_ASP_OFFSETS}")
    print(f"P300_MAG_DSP_HEIGHT = {P300_MAG_DSP_HEIGHT}")
    print(f"P300_MAG_DSP_OFFSETS = {P300_MAG_DSP_OFFSETS}")
    print(f"P300_MAG_REMOVE_ASP_HEIGHT = {P300_MAG_REMOVE_ASP_HEIGHT}")
    print(f"P300_MAG_REMOVE_ASP_OFFSETS = {P300_MAG_REMOVE_ASP_OFFSETS}")
    print(f"P300_WASTE_DSP_HEIGHT = {P300_WASTE_DSP_HEIGHT}")
    print(f"P300_WASTE_DSP_OFFSETS = {P300_WASTE_DSP_OFFSETS}")
    print(f"P300_ADD_BLOWOUT_AIR_VOLUME = {P300_ADD_BLOWOUT_AIR_VOLUME}")
    print(f"P300_REMOVE_BLOWOUT_AIR_VOLUME = {P300_REMOVE_BLOWOUT_AIR_VOLUME}")

    return {
        "p300_tips": p300_tips,
        "mag_96wp": mag_96wp,
        "trough": trough,
    }


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips for wet/reagent run...")
        try:
            await lh.discard_tips()
        except Exception as e:
            print(f"discard_tips failed ({e!r}); returning tips as fallback.")
            await lh.return_tips()
    else:
        print("Returning tips to rack for testing/dev run...")
        await lh.return_tips()


async def run_tip_test(lh: LiquidHandler, r: Dict[str, object], tip_col: int):
    print(f"\n=== TIP TEST: p300 A{tip_col}:H{tip_col} pickup/return ===")
    await lh.pick_up_tips(tips_for_column(r["p300_tips"], tip_col))
    await lh.return_tips()
    print("SUCCESS: p300 pickup/return completed.")


async def add_from_reservoir_to_mag_plate(
    lh: LiquidHandler,
    r: Dict[str, object],
    source_well_name: str,
    dest_cols: List[int],
    vol: float,
    tip_col: int,
    discard_tips: bool,
):
    trough = r["trough"]
    mag_96wp = r["mag_96wp"]
    vols = [vol] * 8

    print("\n=== P300 ADD: reservoir/trough -> rail35 pos1 mag plate ===")
    print(f"Source reservoir well: {source_well_name}; destination columns: {dest_cols}; volume: {vol} uL")
    await lh.pick_up_tips(tips_for_column(r["p300_tips"], tip_col))

    try:
        for dest_col in dest_cols:
            print(f"Aspirating {vol} uL x8 from reservoir {source_well_name}...")
            await lh.aspirate(
                [trough[source_well_name][0]] * 8,
                vols=vols,
                liquid_height=P300_TROUGH_ASP_HEIGHT,
                offsets=P300_TROUGH_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )

            print(f"Dispensing {vol} uL x8 to mag plate column {dest_col}...")
            await lh.dispense(
                wells_for_column(mag_96wp, dest_col),
                vols=vols,
                liquid_height=P300_MAG_DSP_HEIGHT,
                offsets=P300_MAG_DSP_OFFSETS,
                blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8,
            )
    finally:
        await finish_tips(lh, discard_tips=discard_tips)

    print("SUCCESS: p300 reservoir add completed.")


async def remove_from_mag_plate_to_waste(
    lh: LiquidHandler,
    r: Dict[str, object],
    source_cols: List[int],
    waste_well_name: str,
    vol: float,
    tip_col: int,
    discard_tips: bool,
):
    trough = r["trough"]
    mag_96wp = r["mag_96wp"]
    vols = [vol] * 8

    print("\n=== P300 REMOVE: rail35 pos1 mag plate -> reservoir waste ===")
    print(f"Source columns: {source_cols}; waste reservoir well: {waste_well_name}; volume: {vol} uL")
    await lh.pick_up_tips(tips_for_column(r["p300_tips"], tip_col))

    try:
        for source_col in source_cols:
            print(f"Aspirating {vol} uL x8 from mag plate column {source_col} using conservative removal geometry...")
            await lh.aspirate(
                wells_for_column(mag_96wp, source_col),
                vols=vols,
                liquid_height=P300_MAG_REMOVE_ASP_HEIGHT,
                offsets=P300_MAG_REMOVE_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )

            print(f"Dispensing {vol} uL x8 to waste reservoir {waste_well_name}...")
            await lh.dispense(
                [trough[waste_well_name][0]] * 8,
                vols=vols,
                liquid_height=P300_WASTE_DSP_HEIGHT,
                offsets=P300_WASTE_DSP_OFFSETS,
                blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8,
            )
    finally:
        await finish_tips(lh, discard_tips=discard_tips)

    print("SUCCESS: p300 removal-to-waste completed.")


async def main():
    parser = argparse.ArgumentParser(description="p300 ethanol/water add-remove test for rail35 pos3 reservoir and rail35 pos1 mag plate.")
    parser.add_argument(
        "--mode",
        choices=["deck", "tips", "add", "remove", "add-remove"],
        default="deck",
        help="deck=no movement, tips=pickup/return, add=reservoir to mag plate, remove=mag plate to waste, add-remove=both.",
    )
    parser.add_argument(
        "--dest-cols",
        default="1",
        help="Destination/source plate columns. Default: 1.",
    )
    parser.add_argument(
        "--source-well",
        default=TROUGH_ETOH1,
        help=f"Reservoir source well for add. Defaults to {TROUGH_ETOH1}. Use A5 for water/rhodamine test if desired.",
    )
    parser.add_argument(
        "--waste-well",
        default=TROUGH_WASTE,
        help=f"Reservoir waste well for removal. Defaults to {TROUGH_WASTE}.",
    )
    parser.add_argument(
        "--add-vol",
        type=float,
        default=DEFAULT_ADD_VOL,
        help=f"Volume to add from reservoir to mag plate. Default: {DEFAULT_ADD_VOL}.",
    )
    parser.add_argument(
        "--remove-vol",
        type=float,
        default=DEFAULT_REMOVE_VOL,
        help=f"Volume to remove from mag plate to waste. Default: {DEFAULT_REMOVE_VOL}.",
    )
    parser.add_argument(
        "--add-tip-col",
        type=int,
        default=1,
        help="Tip rack column for add step. Default: 1.",
    )
    parser.add_argument(
        "--remove-tip-col",
        type=int,
        default=2,
        help="Tip rack column for remove step. Default: 2.",
    )
    parser.add_argument(
        "--discard-tips",
        action="store_true",
        help="Discard tips instead of returning. Use only for true wet/reagent runs.",
    )
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        resources = await assign_deck(lh)
        dest_cols = parse_cols(args.dest_cols)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No tip pickup or liquid handling executed.")
        elif args.mode == "tips":
            await run_tip_test(lh, resources, tip_col=args.add_tip_col)
        elif args.mode == "add":
            await add_from_reservoir_to_mag_plate(
                lh,
                resources,
                source_well_name=args.source_well,
                dest_cols=dest_cols,
                vol=args.add_vol,
                tip_col=args.add_tip_col,
                discard_tips=args.discard_tips,
            )
        elif args.mode == "remove":
            await remove_from_mag_plate_to_waste(
                lh,
                resources,
                source_cols=dest_cols,
                waste_well_name=args.waste_well,
                vol=args.remove_vol,
                tip_col=args.remove_tip_col,
                discard_tips=args.discard_tips,
            )
        elif args.mode == "add-remove":
            await add_from_reservoir_to_mag_plate(
                lh,
                resources,
                source_well_name=args.source_well,
                dest_cols=dest_cols,
                vol=args.add_vol,
                tip_col=args.add_tip_col,
                discard_tips=args.discard_tips,
            )
            print("NOTE: Use the operator-approved local wash incubation before removal.")
            await remove_from_mag_plate_to_waste(
                lh,
                resources,
                source_cols=dest_cols,
                waste_well_name=args.waste_well,
                vol=args.remove_vol,
                tip_col=args.remove_tip_col,
                discard_tips=args.discard_tips,
            )

    finally:
        print("Stopping STAR backend...")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
