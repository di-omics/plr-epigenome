import argparse
import asyncio
from dataclasses import dataclass
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import PLT_CAR_L5AC_A00, CellTreat_96_wellplate_350ul_Fb, Coordinate
try:
    from pylabrobot.resources.coordinate import Coordinate
except ImportError:
    from pylabrobot.resources import Coordinate
import pylabrobot.resources as plr_resources

# WGS preparation Bio Validation 0 - PTA/WGA beginning
# PTA/WGA SOURCE-TO-WORK LOCK 2026-05-12:
# - Modes are lysis and reaction for the beginning PTA/WGA workflow.
# - lysis adds 3.0 uL Lysis Mix using p10 tip column 1.
# - reaction adds 6.0 uL Reaction Mix using p10 tip column 2.
# - Source is rail35 pos1 column 1 for each mode; manually swap source reagent between modes.
# - Destination/work is rail35 pos0 column 1.
# - p10 source aspiration height = 0.0.
# - p10 work/destination dispense height = 0.5.
# - work/destination dispense XY = Coordinate(-0.68, 3.22, 0.0).
# - p10 blowout = 7.0 uL with 1.0 sec post-dispense settle.
# - Discard tips by default; --return-tips is only for observation.
#
# PRODUCTION GEOMETRY LOCK 2026-05-12:
# - Water test worked when destination wells already contained 3 uL, matching the real DNAPREP input condition.
# - Small-volume modes use p10; LIBAMP uses p50.
# - Source aspiration height = 0.0.
# - Work/destination dispense height = 0.5.
# - Work/destination dispense XY = Coordinate(-0.68, 3.22, 0.0).
# - P10 blowout = 7.0 uL with 1.0 sec post-dispense settle.
# - Default whole-genome amplification map: lysis p10 col1, reaction p10 col2.
#
# P10 WATER-RETENTION TEST PATCH V2:
# - Previous source height -0.5 was rejected by the STAR backend as below minimum well height.
# - Source aspiration height is now 0.0, the lowest legal bottom height.
# - Work/destination dispense height remains 0.5.
# - P10 blowout remains increased to 7.0 uL with 1.0 sec post-dispense settle.
# - Default DNAPREP tip column changed to p10 column 3 because column 2 was picked/discarded during the failed test.
#
# P10 WATER-RETENTION TEST PATCH:
# - Keeps p10 for DNAPREP and small-volume modes.
# - DNAPREP default tip column set to p10 column 2 for this water test.
# - Source aspiration height = -0.5.
# - Work/destination dispense height = 0.5.
# - P10 blowout increased to 7.0 uL with 1.0 sec post-dispense settle.
# - This is a water-only edge test; watch carefully for low-height safety.
#
# P10 LOW-HEIGHT DNAPREP TEST PATCH:
# - Keeps p10 for small-volume modes; p50 remains for LIBAMP.
# - P10 source aspiration height = 0.0.
# - P10 work/destination dispense height = 0.5.
# - P10 blowout = 5.0 uL, with 1.0 sec post-dispense settle before tip discard/return.
# - Default DNAPREP tip column changed to p10 column 8 for fresh upper-column testing.
# - Discard tips remains the default; use --return-tips only if explicitly observing.
#
# SOURCE-HIGHER ASPIRATION PATCH:
# - H=1.0 did not work; it may have been too low / sealing near the bottom.
# - Source aspiration height is now 2.0 for p10 and p50 constants.
# - Source XY kept at Coordinate(-0.65, 3.35, 0.0).
# - Work/destination dispense remains validated at Coordinate(-0.68, 3.22, 0.0), height 3.3.
# - Tip plan unchanged: p10 for 3/4/5/5 uL, p50 for 20 uL LIBAMP.
#
# SOURCE-LOW P10 PATCH V2:
# - H=1.5 picked up better and did not crush, but still looked slightly high/partial.
# - Source aspiration height lowered one more cautious step to 1.0 for p10 and p50 constants.
# - Work/destination dispense remains validated at Coordinate(-0.68, 3.22, 0.0), height 3.3.
# - Tip plan unchanged: p10 for 3/4/5/5 uL, p50 for 20 uL LIBAMP.
#
# SOURCE-LOW P10 PATCH:
# - Keep original best tip plan: p10 for 3/4/5/5 uL, p50 for 20 uL LIBAMP.
# - Empty/under-pickup likely came from source aspiration height being too high.
# - Source aspiration height lowered from 3.3 to 1.5 for p10 and p50 constants.
# - Work/destination dispense remains validated at Coordinate(-0.68, 3.22, 0.0), height 3.3.
# - p10 blowout remains 5.0 uL; p50 blowout remains 6.0 uL.
#
# Y/X-SAFE DISPENSE PATCH V5:
# - Destination/work dispense now uses Coordinate(-0.68, 3.22, 0.0).
# - Source aspiration remains old-safe Coordinate(-0.65, 3.35, 0.0).
# - Y=3.20 previously caused <9 mm adjacent-channel spacing error; this is the cautious edge test.
#
# Y/X-SAFE DISPENSE PATCH V4:
# - y=3.25 was valid and better, but still visually a bit high/back.
# - Destination/work dispense now uses Coordinate(-0.68, 3.23, 0.0).
# - Source aspiration remains old-safe Coordinate(-0.65, 3.35, 0.0).
# - Do not use Y=3.20; that caused <9 mm adjacent-channel spacing error.
#
# Y-SAFE DISPENSE PATCH V3:
# - y=3.30 passed but still looked too far back.
# - Destination/work dispense now nudged lower to Y=3.25.
# - Source aspiration remains old-safe Y=3.35.
# - Do not use Y=3.20; that caused <9 mm adjacent-channel spacing error.
#
# Y-SAFE DISPENSE PATCH V2:
# - y=3.30 was valid but still visually slightly too far back.
# - Destination/work dispense now nudged slightly lower to Y=3.28.
# - Source aspiration remains old-safe Y=3.35.
# - Do not jump to Y=3.20; that caused <9 mm adjacent-channel spacing error.
#
# Y-SAFE DISPENSE PATCH:
# - Bad y=3.20 caused Hamilton/PyLabRobot <9 mm adjacent-channel spacing error.
# - Source aspiration stays at old working Y=3.35.
# - Destination/work dispense gets only a tiny lower/back-forward nudge: Y=3.30.
# - If this is still too far back, tune in tiny steps only; do not jump to Y=3.20.
#
# 03 PRODUCTION staged whole-genome sequencing source-to-work additions, column 1 only, SWAP-SOURCE + DISCARD-TIPS version.
#
# Why this version exists:
# - The 8-strip/source tubes and caps physically cover adjacent columns.
# - Therefore every reagent source is loaded into source 96WP rail35 pos1 COLUMN 1.
# - Between robot steps, the operator swaps/replaces the source strip/tube content in col 1.
# - Each mode performs exactly one reagent addition into destination/work column 1, then stops.
# - Production behavior: tips are discarded by default.
# - Step-specific default tip columns prevent returning to/reusing the same tip position across separate runs.
#
# Deck:
#   rail48 pos0 = p10 tips
#   rail48 pos1 = p50 tips
#   rail35 pos0 = destination/work 96WP or compatible strip/plate
#   rail35 pos1 = chilled source 96WP/strip location; always use column 1
#
# Destination:
#   rail35 pos0 column 1 only.
#
# Source:
#   rail35 pos1 column 1 only, swapped manually between modes:
#     dnaprep = DNA Prep Master Mix, 3 uL, p10
#     ferat   = FERAT Master Mix, 4 uL, p10
#     adapter = Single Use Library Adapter, 5 uL, p10
#     lp2l    = LP2L, 5 uL, p10
#     libamp  = Amplification Master Mix, 20 uL, p50
#
# Cleanup/bead/mag steps are not included here.

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1

SOURCE_COL = 1
DEST_COL = 1

VOL_LYSIS = 3.0
VOL_REACTION = 6.0
VOL_ADAPTER = 5.0
VOL_LP2L = 5.0
VOL_LIBAMP = 20.0

# Validated Bio Validation 0 p10 geometry.
P10_WORK_DSP_HEIGHT = [1.5] * 8
P10_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P10_SOURCE_ASP_HEIGHT = [0.0] * 8
P10_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P10_BLOWOUT_AIR_VOLUME = 7.0

# P50 for LIBAMP uses same x/y and height as the validated column-1 geometry.
# Validate with water before real reagent if needed.
P50_WORK_DSP_HEIGHT = [1.5] * 8
P50_WORK_DSP_OFFSETS = P10_WORK_DSP_OFFSETS
P50_SOURCE_ASP_HEIGHT = [0.0] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0

# Pause after dispense/blowout before returning/discarding tips.
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


STEPS = {
    "lysis": Step(
        "lysis",
        "Lysis Mix",
        VOL_LYSIS,
        "p10",
        "Load source rail35 pos1 column 1 with Lysis Mix (L1/L2/L3). Destination already contains 3 uL Cell Buffer/sample.",
        "seal/spin, then thermal mixer: room temperature 20 min at 1400 rpm; spin and place on ice.",
    ),
    "reaction": Step(
        "reaction",
        "Reaction Mix",
        VOL_REACTION,
        "p10",
        "Load source rail35 pos1 column 1 with Reaction Mix (R1/R2). Destination should already contain 6 uL after lysis addition/incubation.",
        "seal/spin, thermal mixer: room temperature 1 min at 1000 rpm; spin, keep on ice, then load into 30 C DNA Amplification thermocycler.",
    ),
}

# Default production tip columns for separate stepwise runs.
# These are deterministic because the script process restarts between biology steps.
# p10 steps advance across p10 tip rack columns 1-4.
# p50 LIBAMP uses p50 tip rack column 1.
DEFAULT_TIP_COL_BY_MODE = {
    "lysis": 1,
    "reaction": 2,
}


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
    print("Assigning Bio Validation 0 PTA/WGA deck: SWAP-SOURCE column-1 DISCARD-TIP version...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_work_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_chilled_source_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96WP_POS] = source_96wp

    print("\nDeck:")
    print("  rail48 pos0 = p10 tips")
    print("  rail48 pos1 = p50 tips")
    print("  rail35 pos0 = destination/work 96WP, destination column 1")
    print("  rail35 pos1 = chilled source 96WP/strip, SOURCE COLUMN 1 ONLY")
    print("\nSwap-source map:")
    print("  dnaprep: source col 1 = DNA Prep Master Mix, 3 uL")
    print("  ferat:   source col 1 = FERAT Master Mix, 4 uL")
    print("  adapter: source col 1 = Single Use Library Adapter, 5 uL")
    print("  lp2l:    source col 1 = LP2L, 5 uL")
    print("  libamp:  source col 1 = Amplification Master Mix, 20 uL")
    print("\nP10 geometry:")
    print(f"  P10_SOURCE_ASP_HEIGHT = {P10_SOURCE_ASP_HEIGHT}")
    print(f"  P10_SOURCE_ASP_OFFSETS = {P10_SOURCE_ASP_OFFSETS}")
    print(f"  P10_WORK_DSP_HEIGHT = {P10_WORK_DSP_HEIGHT}")
    print(f"  P10_WORK_DSP_OFFSETS = {P10_WORK_DSP_OFFSETS}")
    print(f"  P10_BLOWOUT_AIR_VOLUME = {P10_BLOWOUT_AIR_VOLUME}")
    print("\nP50 geometry:")
    print(f"  P50_SOURCE_ASP_HEIGHT = {P50_SOURCE_ASP_HEIGHT}")
    print(f"  P50_SOURCE_ASP_OFFSETS = {P50_SOURCE_ASP_OFFSETS}")
    print(f"  P50_WORK_DSP_HEIGHT = {P50_WORK_DSP_HEIGHT}")
    print(f"  P50_WORK_DSP_OFFSETS = {P50_WORK_DSP_OFFSETS}")
    print(f"  P50_BLOWOUT_AIR_VOLUME = {P50_BLOWOUT_AIR_VOLUME}")

    return {"p10_tips": p10_tips, "p50_tips": p50_tips, "work_plate": work_plate, "source_96wp": source_96wp}


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips...")
        await lh.discard_tips()
    else:
        print("Returning tips to rack...")
        await lh.return_tips()



async def transfer_step(lh: LiquidHandler, r: Dict[str, object], step: Step, discard_tips: bool, tip_col: int):
    vols = [step.volume_ul] * 8

    if step.tip_type == "p10":
        tips = r["p10_tips"][f"A{tip_col}:H{tip_col}"]
        asp_height, asp_offsets = P10_SOURCE_ASP_HEIGHT, P10_SOURCE_ASP_OFFSETS
        dsp_height, dsp_offsets = P10_WORK_DSP_HEIGHT, P10_WORK_DSP_OFFSETS
        blowout = P10_BLOWOUT_AIR_VOLUME
    elif step.tip_type == "p50":
        tips = r["p50_tips"][f"A{tip_col}:H{tip_col}"]
        asp_height, asp_offsets = P50_SOURCE_ASP_HEIGHT, P50_SOURCE_ASP_OFFSETS
        dsp_height, dsp_offsets = P50_WORK_DSP_HEIGHT, P50_WORK_DSP_OFFSETS
        blowout = P50_BLOWOUT_AIR_VOLUME
    else:
        raise RuntimeError(f"Unknown tip_type: {step.tip_type}")

    dest_cols = list(range(1, 13))

    print("")
    print(f"=== FULL-PLATE DRY DEMO {step.mode.upper()}: {step.label} ===")
    print("DRY DEMO ONLY: source rail35 pos1 column 1 A-H -> destination rail35 pos0 columns 1-12 A-H")
    print(f"PREP: {step.manual_prep}")
    print(f"Source rail35 pos1 col {SOURCE_COL} -> destination rail35 pos0 cols 1-12")
    print(f"Volume per destination column: {step.volume_ul} uL x8")
    print(f"Total destination columns: {len(dest_cols)}")
    print(f"Tip type: {step.tip_type}; tip column {tip_col}; discard_tips={discard_tips}")
    print("One STAR init, one tip pickup, repeated source-col1 aspirate -> destination-column dispense loop.")

    await lh.pick_up_tips(tips)
    try:
        for dest_col in dest_cols:
            print("")
            print(f"Destination column {dest_col} / 12")
            print(f"  Aspirating {step.volume_ul} uL x8 from source 96WP col {SOURCE_COL}...")
            await lh.aspirate(
                r["source_96wp"][f"A{SOURCE_COL}:H{SOURCE_COL}"],
                vols=vols,
                liquid_height=asp_height,
                offsets=asp_offsets,
                blow_out_air_volume=[0.0] * 8,
            )

            print(f"  Dispensing {step.volume_ul} uL x8 to destination 96WP col {dest_col} with blowout {blowout} uL...")
            await lh.dispense(
                wells_for_column(r["work_plate"], dest_col),
                vols=vols,
                liquid_height=dsp_height,
                offsets=dsp_offsets,
                blow_out_air_volume=[blowout] * 8,
            )
            print(f"  Post-dispense settle: {POST_DISPENSE_SETTLE_SECONDS} sec")
            await asyncio.sleep(POST_DISPENSE_SETTLE_SECONDS)

        print("")
        print("SUCCESS: Full-plate source-col1 -> destination cols 1-12 dry demo motion completed.")
    finally:
        await finish_tips(lh, discard_tips)



async def move_work_plate_to_hhs_pos2(lh: LiquidHandler, r: Dict[str, object], drop_x: float, drop_y: float, drop_z: float):
    print("")
    print("=== iSWAP MOVE: work plate rail35 pos0 -> HHS rail27 pos2 ===")
    print(f"Drop offsets: X +{drop_x} mm, Y +{drop_y} mm, Z +{drop_z} mm")
    print("Destination HHS/plate holder must be physically empty. Hand near E-stop.")

    drop_carrier = PLT_CAR_L5AC_A00(name="iswap_hhs_drop_carrier_rail27")
    lh.deck.assign_child_resource(drop_carrier, rails=27)

    drop_site = drop_carrier[2]
    base = drop_site.location
    drop_site.location = Coordinate(base.x + drop_x, base.y + drop_y, base.z + drop_z)

    print(f"Drop base location:    {base}")
    print(f"Drop shifted location: {drop_site.location}")

    async with lh.backend.slow_iswap():
        await lh.move_resource(r["work_plate"], drop_site)

    print("SUCCESS: iSWAP moved work plate to HHS rail27 pos2.")


async def run_all_dev(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool):
    print("\n=== ALL-DEV WATER ONLY ===")
    print("WARNING: source column 1 cannot contain all real reagents at once.")
    print("This mode is only for water/dry logic checking with the same source col 1 liquid.")
    print("For real biology, run each mode separately and swap source col 1 between runs. This production version discards tips by default.")

    p10_col = 1
    p50_col = 1
    for mode in ["dnaprep", "ferat", "adapter", "lp2l"]:
        await transfer_step(lh, r, STEPS[mode], discard_tips, tip_col=p10_col)
        if discard_tips:
            p10_col += 1
    await transfer_step(lh, r, STEPS["libamp"], discard_tips, tip_col=p50_col)
    print("\nSUCCESS: all-dev water-only source-to-work additions completed.")


async def main():
    parser = argparse.ArgumentParser(description="PTA/WGA full-plate dry demo: source column 1 to destination columns 1-12 with 1.5 mm destination dispense height.")
    parser.add_argument("--mode", choices=["deck", "lysis", "reaction", "all-dev", "full-demo-iswap"], default="deck")
    parser.add_argument("--return-tips", action="store_true", help="Return tips instead of discarding. Default is production-style discard.")
    parser.add_argument(
        "--tip-col",
        type=int,
        default=None,
        help=(
            "Override tip column for this isolated step. Default production map: "
            "dnaprep p10 col1, ferat p10 col2, adapter p10 col3, lp2l p10 col4, libamp p50 col1."
        ),
    )
    parser.add_argument("--confirm", default="")
    parser.add_argument("--iswap-drop-x-offset-mm", type=float, default=14.0)
    parser.add_argument("--iswap-drop-y-offset-mm", type=float, default=47.5)
    parser.add_argument("--iswap-drop-z-offset-mm", type=float, default=7.0)
    args = parser.parse_args()

    discard_tips = not args.return_tips

    if args.tip_col is not None and (args.tip_col < 1 or args.tip_col > 12):
        raise ValueError("--tip-col must be 1..12")

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No movement or liquid handling executed.")
            return

        if args.mode == "full-demo-iswap":
            if args.confirm != "RUN_FULL_PTA_ISWAP_DEMO":
                raise RuntimeError("Refusing to run full demo. Add: --confirm RUN_FULL_PTA_ISWAP_DEMO")
            if discard_tips:
                raise RuntimeError("This dry video/demo mode requires --return-tips")

            print("Running full 96WP dry demo in one STAR init:")
            print("  1. lysis source col1 -> destination cols 1-12")
            print("  2. reaction source col1 -> destination cols 1-12")
            print("  3. iSWAP work plate to HHS rail27 pos2")

            await transfer_step(
                lh,
                r,
                STEPS["lysis"],
                discard_tips,
                tip_col=DEFAULT_TIP_COL_BY_MODE["lysis"],
            )
            await transfer_step(
                lh,
                r,
                STEPS["reaction"],
                discard_tips,
                tip_col=DEFAULT_TIP_COL_BY_MODE["reaction"],
            )
            await move_work_plate_to_hhs_pos2(
                lh,
                r,
                drop_x=args.iswap_drop_x_offset_mm,
                drop_y=args.iswap_drop_y_offset_mm,
                drop_z=args.iswap_drop_z_offset_mm,
            )
            return

        if args.mode in STEPS:
            step_tip_col = args.tip_col if args.tip_col is not None else DEFAULT_TIP_COL_BY_MODE[args.mode]
            print(f"Production tip behavior: discard_tips={discard_tips}; selected tip column={step_tip_col}")
            await transfer_step(lh, r, STEPS[args.mode], discard_tips, tip_col=step_tip_col)
            return

        if args.mode == "all-dev":
            print(f"Production tip behavior: discard_tips={discard_tips}")
            await run_all_dev(lh, r, discard_tips)
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
