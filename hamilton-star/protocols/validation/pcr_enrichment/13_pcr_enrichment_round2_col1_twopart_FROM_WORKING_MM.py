import argparse
import asyncio
from dataclasses import dataclass
from typing import Dict, List

from pathlib import Path as _MethodPath
import sys as _method_sys

_method_root = next(parent for parent in _MethodPath(__file__).resolve().parents if parent.name == "hamilton-star")
if str(_method_root) not in _method_sys.path:
    _method_sys.path.insert(0, str(_method_root))
from operator_parameters import required_positive, required_nonnegative, required_text

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import PLT_CAR_L5AC_A00, CellTreat_96_wellplate_350ul_Fb, Coordinate
import pylabrobot.resources as plr_resources

# PCR enrichment library preparation - operator-volume round 2 reagent addition
#
# Purpose:
# - Keep the existing WGS/validation deck unchanged.
# - Transfer an operator-prepared round 2 reagent using validated motion geometry.
# - Destination inputs are prepared according to the operator-approved local SOP.
# - Transfer volume comes from the operator-approved local method profile.
# - Dry observation: run with --return-tips.
# - Production behavior: discards tips by default if --return-tips is omitted.
#
# Deck:
#   rail48 pos0 = p10 tips
#   rail48 pos1 = p50 tips
#   rail35 pos0 = destination/work 96WP or compatible strip/plate, column 1
#   rail35 pos1 = source 96WP/strip/reagent plate, full 96WP dry demo
#
# Reaction composition and thermal conditions are intentionally kept in the
# operator-approved local SOP, not in this public hardware-control script.

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1

SOURCE_COL = 1
DEST_COL = 1
DEST_COLS = [1]

VOL_PCR1_MASTER_MIX = required_positive("pcr_enrichment.round_1_transfer_ul")
VOL_PCR2_MASTER_MIX = required_positive("pcr_enrichment.round_2_transfer_ul")
THERMAL_PROGRAM_ID = required_text("pcr_enrichment.thermal_program_id")
PCR1_SOURCE_COL = 1
PCR2_SOURCE_COL = 3

# Reuse the validated validation column-1 P50 geometry.
P50_WORK_DSP_HEIGHT = [1.5] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(-0.38, 3.22, 0.0)] * 8
P50_SOURCE_ASP_HEIGHT = [0.9] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0

# Define p10 resources too so deck layout stays identical, although PCR1-MM uses p50.
P10_WORK_DSP_HEIGHT = [1.5] * 8
P10_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P10_SOURCE_ASP_HEIGHT = [0.0] * 8
P10_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P10_BLOWOUT_AIR_VOLUME = 7.0

POST_DISPENSE_SETTLE_SECONDS = 1.0

P10_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_10uL_filter", "hamilton_96_tiprack_10ul_filter"]
P50_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_50uL_filter", "hamilton_96_tiprack_50ul_filter"]


@dataclass
class Step:
    mode: str
    label: str
    volume_ul: float
    tip_type: str
    manual_prep: str
    manual_stop: str


PCR1_MM_STEP = Step(
    mode="pcr1-mm",
    label="PCR enrichment round 1 reagent",
    volume_ul=VOL_PCR1_MASTER_MIX,
    tip_type="p50",
    manual_prep=(
        "Prepare destination and source wells according to the operator-approved local SOP. "
        "Load the approved PCR enrichment reagent in source rail35 pos1."
    ),
    manual_stop=f"Seal/spin, then run operator-approved off-deck program: {THERMAL_PROGRAM_ID}.",
)


def make_resource(label: str, name: str, candidates: List[str], terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)
    terms_lower = [term.lower() for term in terms]
    available = sorted(n for n in dir(plr_resources) if any(term in n.lower() for term in terms_lower))
    raise RuntimeError(f"Could not find factory for {label}. Tried {candidates}. Nearby: {available[:80]}")


def make_p10_tips(name: str):
    return make_resource("p10 filter tips", name, P10_TIP_FACTORY_CANDIDATES, ["tip", "10"])


def make_p50_tips(name: str):
    return make_resource("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES, ["tip", "50"])


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning PCR enrichment operator-volume round 2 deck: WGS/validation compatible layout...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_pcr_enrichment_round1_dest_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_pcr_enrichment_round1_mm_source_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96WP_POS] = source_96wp

    print("\nDeck:")
    print("  rail48 pos0 = p10 tips, present for deck compatibility")
    print("  rail48 pos1 = p50 tips, used for PCR1/PCR2 master mix")
    print("  rail35 pos0 = destination/work 96WP or strip, destination columns 1-12")
    print("  rail35 pos1 = source 96WP/strip, SOURCE COL1 PCR1, SOURCE COL3 PCR2")
    print("\nPCR1 master-mix mode:")
    print("  destination cols 1-12 A-H start with template/control or staged PCR2 inputs")
    print("  source col1 A-H = complete PCR1 MM; source col3 A-H = common PCR2 MM")
    print(f"  transfer = {VOL_PCR1_MASTER_MIX} uL x8 by p50")
    print("\nP50 geometry:")
    print(f"  P50_SOURCE_ASP_HEIGHT = {P50_SOURCE_ASP_HEIGHT}")
    print(f"  P50_SOURCE_ASP_OFFSETS = {P50_SOURCE_ASP_OFFSETS}")
    print(f"  P50_WORK_DSP_HEIGHT = {P50_WORK_DSP_HEIGHT}")
    print(f"  P50_WORK_DSP_OFFSETS = {P50_WORK_DSP_OFFSETS}")
    print(f"  P50_BLOWOUT_AIR_VOLUME = {P50_BLOWOUT_AIR_VOLUME}")

    return {
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "work_plate": work_plate,
        "source_96wp": source_96wp,
    }


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips...")
        await lh.discard_tips()
    else:
        print("Returning tips to rack...")
        await lh.return_tips()



async def transfer_master_mix_96wp(
    lh: LiquidHandler,
    r: Dict[str, object],
    *,
    label: str,
    volume_ul: float,
    source_col: int,
    tip_col: int,
    discard_tips: bool,
):
    vols = [volume_ul] * 8
    tips = r["p50_tips"][f"A{tip_col}:H{tip_col}"]

    print("")
    print(f"=== PCR ENRICHMENT 96WP DRY DEMO: {label} ===")
    print("DRY DEMO ONLY: source rail35 pos1 selected column A-H -> destination rail35 pos0 columns 1-12 A-H")
    print(f"Source rail35 pos1 col {source_col} -> destination rail35 pos0 cols 1-12")
    print(f"Volume per destination column: {volume_ul} uL x8")
    print(f"Total destination columns: {len(DEST_COLS)}")
    print(f"Tip type: p50; tip column {tip_col}; discard_tips={discard_tips}")
    print("One STAR init, one tip pickup per step, repeated selected-source-column aspirate -> destination-column dispense loop.")
    print(f"P50_SOURCE_ASP_HEIGHT = {P50_SOURCE_ASP_HEIGHT}")
    print(f"P50_WORK_DSP_HEIGHT = {P50_WORK_DSP_HEIGHT}")
    print(f"P50_BLOWOUT_AIR_VOLUME = {P50_BLOWOUT_AIR_VOLUME}")

    await lh.pick_up_tips(tips)
    try:
        for dest_col in DEST_COLS:
            print("")
            print(f"Destination column {dest_col} / 12")
            print(f"  Aspirating {volume_ul} uL x8 from source 96WP col {source_col}...")
            await lh.aspirate(
                r["source_96wp"][f"A{source_col}:H{source_col}"],
                vols=vols,
                liquid_height=P50_SOURCE_ASP_HEIGHT,
                offsets=P50_SOURCE_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )

            print(f"  Dispensing {volume_ul} uL x8 to destination 96WP col {dest_col} with blowout {P50_BLOWOUT_AIR_VOLUME} uL...")
            await lh.dispense(
                wells_for_column(r["work_plate"], dest_col),
                vols=vols,
                liquid_height=P50_WORK_DSP_HEIGHT,
                offsets=P50_WORK_DSP_OFFSETS,
                blow_out_air_volume=[P50_BLOWOUT_AIR_VOLUME] * 8,
            )
            print("  Post-dispense settle: 1.0 sec")
            await asyncio.sleep(1.0)

        print("")
        print(f"SUCCESS: {label} full-plate selected-source-column -> destination cols 1-12 dry demo completed.")
    finally:
        await finish_tips(lh, discard_tips)


async def transfer_pcr1_master_mix(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, tip_col: int):
    await transfer_master_mix_96wp(
        lh,
        r,
        label="PCR1 master mix",
        volume_ul=VOL_PCR1_MASTER_MIX,
        source_col=PCR1_SOURCE_COL,
        tip_col=tip_col,
        discard_tips=discard_tips,
    )


async def transfer_pcr2_master_mix(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, tip_col: int):
    await transfer_master_mix_96wp(
        lh,
        r,
        label="PCR2 common master mix",
        volume_ul=VOL_PCR2_MASTER_MIX,
        source_col=PCR2_SOURCE_COL,
        tip_col=tip_col,
        discard_tips=discard_tips,
    )



async def main():
    parser = argparse.ArgumentParser(
        description="PCR enrichment round 2 operator-volume setup using working liquid-handling geometry."
    )
    parser.add_argument(
        "--mode",
        choices=["deck", "pcr1-mm", "pcr2-mm", "full-mm-demo"],
        default="deck",
    )
    parser.add_argument(
        "--return-tips",
        action="store_true",
        help="Return tips to rack instead of discarding. Use for dry/demo validation.",
    )
    parser.add_argument(
        "--tip-col",
        type=int,
        default=1,
        help="P50 tip column for single-step mode. Default: 1 for PCR1; PCR2 defaults to 2 if not overridden.",
    )
    args = parser.parse_args()

    discard_tips = not args.return_tips

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No liquid handling executed.")
            return

        if args.mode == "pcr1-mm":
            print(f"Production tip behavior: discard_tips={discard_tips}; selected p50 tip column={args.tip_col}")
            await transfer_pcr1_master_mix(lh, r, discard_tips, tip_col=args.tip_col)
            return

        if args.mode == "pcr2-mm":
            tip_col = args.tip_col if args.tip_col != 1 else 2
            print(f"Production tip behavior: discard_tips={discard_tips}; selected p50 tip column={tip_col}")
            await transfer_pcr2_master_mix(lh, r, discard_tips, tip_col=tip_col)
            return

        if args.mode == "full-mm-demo":
            print(f"Production tip behavior: discard_tips={discard_tips}")
            print("Running full PCR enrichment 96WP dry demo in one STAR init:")
            print("  1. PCR1 MM source col1 -> destination cols 1-12")
            print("  2. PCR2 MM source col3 -> destination cols 1-12")
            await transfer_pcr1_master_mix(lh, r, discard_tips, tip_col=1)
            await transfer_pcr2_master_mix(lh, r, discard_tips, tip_col=2)
            return

        raise RuntimeError(f"Unhandled mode: {args.mode}")

    finally:
        print("Stopping STAR backend...")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
