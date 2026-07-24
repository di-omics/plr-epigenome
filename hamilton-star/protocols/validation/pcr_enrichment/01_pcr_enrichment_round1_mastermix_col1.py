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

# PCR enrichment library preparation - round 1 reagent addition, column 1 only
#
# Purpose:
# - Keep the existing WGS/validation deck unchanged.
# - First low-risk PCR enrichment automation target: add an operator-prepared round 1 reagent.
# - Template DNA is assumed to already be in destination/work column 1.
# - Transfer volume comes from the operator-approved local method profile.
# - Dry observation: run with --return-tips.
# - Production behavior: discards tips by default if --return-tips is omitted.
#
# Deck:
#   rail48 pos0 = p10 tips
#   rail48 pos1 = p50 tips
#   rail35 pos0 = destination/work 96WP or compatible strip/plate, column 1
#   rail35 pos1 = source 96WP/strip/reagent plate, column 1 only
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

VOL_PCR1_MASTER_MIX = required_positive("pcr_enrichment.round_1_transfer_ul")
THERMAL_PROGRAM_ID = required_text("pcr_enrichment.thermal_program_id")

# Reuse the validated validation column-1 P50 geometry.
P50_WORK_DSP_HEIGHT = [0.5] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P50_SOURCE_ASP_HEIGHT = [0.0] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0

# Define p10 resources too so deck layout stays identical, although PCR1-MM uses p50.
P10_WORK_DSP_HEIGHT = [0.5] * 8
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
        "Load the approved round 1 reagent in source rail35 pos1 column 1."
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
    print("Assigning PCR enrichment round 1 deck: WGS/validation compatible column-1 layout...")

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
    print("  rail48 pos1 = p50 tips, used for PCR1 master mix")
    print("  rail35 pos0 = destination/work 96WP or strip, destination column 1")
    print("  rail35 pos1 = source 96WP/strip, SOURCE COLUMN 1 ONLY")
    print("\nPCR1 master-mix mode:")
    print("  destination col 1 A-H is staged per the operator-approved local SOP")
    print("  source col 1 A-H contains complete PCR1 master mix")
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


async def transfer_pcr1_master_mix(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, tip_col: int):
    step = PCR1_MM_STEP
    vols = [step.volume_ul] * 8

    tips = r["p50_tips"][f"A{tip_col}:H{tip_col}"]

    print(f"\n=== {step.mode.upper()}: {step.label} ===")
    print(f"PREP: {step.manual_prep}")
    print(f"Source rail35 pos1 col {SOURCE_COL} -> destination rail35 pos0 col {DEST_COL}")
    print(f"Volume: {step.volume_ul} uL x8")
    print(f"Tip type: p50; tip column {tip_col}; discard_tips={discard_tips}")

    await lh.pick_up_tips(tips)
    try:
        print(f"Aspirating {step.volume_ul} uL x8 from PCR1 master-mix source col {SOURCE_COL}...")
        await lh.aspirate(
            wells_for_column(r["source_96wp"], SOURCE_COL),
            vols=vols,
            liquid_height=P50_SOURCE_ASP_HEIGHT,
            offsets=P50_SOURCE_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )

        print(f"Dispensing {step.volume_ul} uL x8 to destination col {DEST_COL} with blowout {P50_BLOWOUT_AIR_VOLUME} uL...")
        print(f"Post-dispense settle before tip return/discard: {POST_DISPENSE_SETTLE_SECONDS} sec")
        await lh.dispense(
            wells_for_column(r["work_plate"], DEST_COL),
            vols=vols,
            liquid_height=P50_WORK_DSP_HEIGHT,
            offsets=P50_WORK_DSP_OFFSETS,
            blow_out_air_volume=[P50_BLOWOUT_AIR_VOLUME] * 8,
        )
        await asyncio.sleep(POST_DISPENSE_SETTLE_SECONDS)
    finally:
        await finish_tips(lh, discard_tips)

    print(f"\nSUCCESS: {step.label} addition completed.")
    print(step.manual_stop)


async def main():
    parser = argparse.ArgumentParser(
        description="PCR enrichment round 1 reagent addition, column 1, WGS/validation compatible deck."
    )
    parser.add_argument("--mode", choices=["deck", "pcr1-mm"], default="deck")
    parser.add_argument(
        "--return-tips",
        action="store_true",
        help="Return tips instead of discarding. Use this for dry observation. Default is production-style discard.",
    )
    parser.add_argument(
        "--tip-col",
        type=int,
        default=1,
        help="P50 tip column to use for pcr1-mm. Default: 1.",
    )
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

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

        raise RuntimeError(f"Unhandled mode: {args.mode}")

    finally:
        print("Stopping STAR backend...")
        try:
            await lh.backend.park_iswap()
        except Exception as e:
            print(f"park_iswap warning: {e!r}")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
