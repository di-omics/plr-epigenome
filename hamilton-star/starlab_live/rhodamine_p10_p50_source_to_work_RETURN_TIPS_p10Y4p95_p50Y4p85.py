import argparse
import asyncio
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.standard import Mix
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# -----------------------------------------------------------------------------
# whole-genome sequencing - p10 + p50 source-to-work RHODAMINE / LH geometry script
# Hamilton STAR + PyLabRobot on starpi
#
# Purpose:
# - Today objective: rhodamine B liquid-handling QC for source 96DW -> work 96WP.
# - Runs only p10 and p50 source-to-work additions.
# - Later branch idea: p50-for-all version for accuracy comparison; not enabled here.
# - Excludes p300 cleanup, reservoir/trough, removals, and iSWAP.
# - iSWAP will be tested separately later as rail35 pos0 -> rail35 pos1.
#
# Safety:
# - Always uses lh.setup(skip_autoload=True).
# - No autoload.
# - Testing-phase behavior: return tips by default.
# - To discard tips for a true wet/reagent run, pass --discard-tips.
#
# Active deck:
# - Rail 48 pos0 = p10 filter tips
# - Rail 48 pos1 = p50 filter tips
# - Rail 35 pos0 = work 96WP
# - Rail 35 pos2 = source 96DW
#
# Tuned geometry from p10 refine, copied to p50:
# - Source 96DW aspirate:
#   p10 height = 13.0, offset = Coordinate(0.35, 4.95, 0.0)
#   p50 height = 11.5, offset = Coordinate(0.35, 4.85, 0.0)
#   Note: p10 Y is set to 4.95 after source aspirate edge observation; p50 remains at 4.85.
# - Work 96WP dispense, p10 + p50:
#   height = 16.0
#   offset = Coordinate(-0.15, 3.35, 0.0)
# -----------------------------------------------------------------------------

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

LABWARE_RAIL = 35
WORK_96WP_POS = 0
SOURCE_96DW_POS = 2

# Default: column 1 only for A1:H1 rhodamine validation.
DEST_COLUMNS = [1]

# Final-ish p10-refined source/work geometry.
P10_SOURCE_96DW_ASP_HEIGHT = [13.0] * 8
P10_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 4.95, 0.0)] * 8

# p50 uses the same XY source offset but lower aspirate height because the p50 pickup/path
# looked too high during observation.
P50_SOURCE_96DW_ASP_HEIGHT = [11.5] * 8
P50_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 4.85, 0.0)] * 8

WORK_96WP_DSP_HEIGHT = [16.0] * 8
WORK_96WP_DSP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8

# Blowout tuning for rhodamine QC.
# p10 additions are 3-6 uL: modest blowout to reduce hanging droplets without splashing.
P10_BLOWOUT_AIR_VOLUME = 1.0
# p50 is used for the 20 uL step.
P50_BLOWOUT_AIR_VOLUME = 2.0

# Keep mix off by default for rhodamine placement/CV observation to avoid bubbles/splashing.
MIX_REPETITIONS = 0
MIX_FLOW_RATE = 80

# whole-genome sequencing source 96DW layout.
SRC_LYSIS_COL = 1
SRC_REACTION_COL = 2
SRC_DNAPREP_COL = 3
SRC_FERAT_COL = 4
SRC_ADAPTER_COL = 5
SRC_LP2L_COL = 6
SRC_LIBAMP_COL = 7

# Protocol volumes.
VOL_LYSIS = 3.0
VOL_REACTION = 6.0
VOL_DNAPREP = 3.0
VOL_FERAT = 4.0
VOL_ADAPTER = 5.0
VOL_LP2L = 5.0
VOL_LIBAMP = 20.0

P10_STEPS = [
    (SRC_LYSIS_COL, VOL_LYSIS, "Lysis Mix / rhodamine source col 1"),
    (SRC_REACTION_COL, VOL_REACTION, "Reaction Mix / rhodamine source col 2"),
    (SRC_DNAPREP_COL, VOL_DNAPREP, "DNA Prep Master Mix / rhodamine source col 3"),
    (SRC_FERAT_COL, VOL_FERAT, "FERAT Master Mix / rhodamine source col 4"),
    (SRC_ADAPTER_COL, VOL_ADAPTER, "UDI Adapters / rhodamine source col 5"),
    (SRC_LP2L_COL, VOL_LP2L, "LP2L / rhodamine source col 6"),
]

P50_STEPS = [
    (SRC_LIBAMP_COL, VOL_LIBAMP, "Amplification Master Mix / rhodamine source col 7"),
]

P10_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_10uL_filter",
    "hamilton_96_tiprack_10ul_filter",
]

P50_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_50uL_filter",
    "hamilton_96_tiprack_50ul_filter",
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


def make_p50_tiprack(name: str):
    return make_resource_from_candidates(
        "p50 filter tips",
        name,
        P50_TIP_FACTORY_CANDIDATES,
        nearby_terms=["tip", "50", "htf"],
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


def mix_after_dispense(vol: float):
    if MIX_REPETITIONS <= 0:
        return None
    mix_vol = max(1.0, min(float(vol), 20.0))
    return [Mix(volume=mix_vol, repetitions=MIX_REPETITIONS, flow_rate=MIX_FLOW_RATE)] * 8


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning p10+p50 rhodamine deck resources...")

    tip_carrier_48 = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")

    lh.deck.assign_child_resource(tip_carrier_48, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tiprack(name="r48_p10_filter_tips")
    p50_tips = make_p50_tiprack(name="r48_p50_filter_tips")
    source_96dw = make_96dw_source_plate(name="rail35_pos2_source_96dw")
    work_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_work_96wp")

    tip_carrier_48[P10_TIP_POS] = p10_tips
    tip_carrier_48[P50_TIP_POS] = p50_tips
    labware_carrier[WORK_96WP_POS] = work_96wp
    labware_carrier[SOURCE_96DW_POS] = source_96dw

    print("\nAssigned resources:")
    print(f"tip_carrier_48: {tip_carrier_48.location}")
    print(f"labware_carrier: {labware_carrier.location}")
    print(f"p10_tips: {p10_tips.location}")
    print(f"p50_tips: {p50_tips.location}")
    print(f"source_96dw: {source_96dw.location}")
    print(f"work_96wp: {work_96wp.location}")

    print("\nTuned source/work geometry:")
    print(f"P10_SOURCE_96DW_ASP_HEIGHT = {P10_SOURCE_96DW_ASP_HEIGHT}")
    print(f"P10_SOURCE_96DW_ASP_OFFSETS = {P10_SOURCE_96DW_ASP_OFFSETS}")
    print(f"P50_SOURCE_96DW_ASP_HEIGHT = {P50_SOURCE_96DW_ASP_HEIGHT}")
    print(f"P50_SOURCE_96DW_ASP_OFFSETS = {P50_SOURCE_96DW_ASP_OFFSETS}")
    print(f"WORK_96WP_DSP_HEIGHT = {WORK_96WP_DSP_HEIGHT}")
    print(f"WORK_96WP_DSP_OFFSETS = {WORK_96WP_DSP_OFFSETS}")
    print(f"P10_BLOWOUT_AIR_VOLUME = {P10_BLOWOUT_AIR_VOLUME}")
    print(f"P50_BLOWOUT_AIR_VOLUME = {P50_BLOWOUT_AIR_VOLUME}")

    return {
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "source_96dw": source_96dw,
        "work_96wp": work_96wp,
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


async def transfer_column(
    lh: LiquidHandler,
    source_wells,
    target_wells,
    vol: float,
    asp_height: List[float],
    asp_offsets: List[Coordinate],
    blowout_air_volume: float,
    label: str,
    do_mix: bool = False,
):
    vols = [vol] * 8

    print(f"Aspirating {vol} uL from {label}...")
    await lh.aspirate(
        source_wells,
        vols=vols,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL to work 96WP using tuned p10/p50 geometry...")
    kwargs = {}
    mix = mix_after_dispense(vol) if do_mix else None
    if mix is not None:
        kwargs["mix"] = mix

    await lh.dispense(
        target_wells,
        vols=vols,
        liquid_height=WORK_96WP_DSP_HEIGHT,
        offsets=WORK_96WP_DSP_OFFSETS,
        blow_out_air_volume=[blowout_air_volume] * 8,
        **kwargs,
    )


async def run_tip_test(lh: LiquidHandler, resources: Dict[str, object]):
    print("\n=== TIP TEST: p10 + p50 A1:H1 pickup/return ===")
    await lh.pick_up_tips(resources["p10_tips"]["A1:H1"])
    await lh.return_tips()
    print("SUCCESS: p10 pickup/return completed.")

    await lh.pick_up_tips(resources["p50_tips"]["A1:H1"])
    await lh.return_tips()
    print("SUCCESS: p50 pickup/return completed.")


async def run_p10_steps(
    lh: LiquidHandler,
    resources: Dict[str, object],
    source_cols: List[int],
    dest_cols: List[int],
    discard_tips: bool,
    do_mix: bool,
):
    selected_steps = [step for step in P10_STEPS if step[0] in source_cols]
    if not selected_steps:
        print("No p10 steps selected; skipping p10.")
        return

    source_96dw = resources["source_96dw"]
    work_96wp = resources["work_96wp"]

    print("\n=== P10 RHODAMINE / SMALL-VOLUME SOURCE-TO-WORK STEPS ===")
    print(f"Selected p10 source columns: {source_cols}")
    print(f"Destination columns: {dest_cols}")
    await lh.pick_up_tips(resources["p10_tips"]["A1:H1"])

    try:
        for dest_col in dest_cols:
            for src_col, vol, label in selected_steps:
                await transfer_column(
                    lh,
                    source_96dw[f"A{src_col}:H{src_col}"],
                    wells_for_column(work_96wp, dest_col),
                    vol,
                    P10_SOURCE_96DW_ASP_HEIGHT,
                    P10_SOURCE_96DW_ASP_OFFSETS,
                    P10_BLOWOUT_AIR_VOLUME,
                    label,
                    do_mix=do_mix,
                )
    finally:
        await finish_tips(lh, discard_tips=discard_tips)

    print("SUCCESS: p10 source-to-work steps completed.")


async def run_p50_steps(
    lh: LiquidHandler,
    resources: Dict[str, object],
    source_cols: List[int],
    dest_cols: List[int],
    discard_tips: bool,
    do_mix: bool,
):
    selected_steps = [step for step in P50_STEPS if step[0] in source_cols]
    if not selected_steps:
        print("No p50 steps selected; skipping p50.")
        return

    source_96dw = resources["source_96dw"]
    work_96wp = resources["work_96wp"]

    print("\n=== P50 RHODAMINE / 20 UL SOURCE-TO-WORK STEP ===")
    print(f"Selected p50 source columns: {source_cols}")
    print(f"Destination columns: {dest_cols}")
    await lh.pick_up_tips(resources["p50_tips"]["A1:H1"])

    try:
        for dest_col in dest_cols:
            for src_col, vol, label in selected_steps:
                await transfer_column(
                    lh,
                    source_96dw[f"A{src_col}:H{src_col}"],
                    wells_for_column(work_96wp, dest_col),
                    vol,
                    P50_SOURCE_96DW_ASP_HEIGHT,
                    P50_SOURCE_96DW_ASP_OFFSETS,
                    P50_BLOWOUT_AIR_VOLUME,
                    label,
                    do_mix=do_mix,
                )
    finally:
        await finish_tips(lh, discard_tips=discard_tips)

    print("SUCCESS: p50 source-to-work steps completed.")


async def main():
    parser = argparse.ArgumentParser(description="p10+p50-only rhodamine source-to-work test for STAR rail48/rail35 layout.")
    parser.add_argument(
        "--mode",
        choices=["deck", "tips", "p10", "p50", "rhodamine"],
        default="deck",
        help="deck=no movement, tips=pickup/return, p10=p10 only, p50=p50 only, rhodamine=p10 then p50.",
    )
    parser.add_argument(
        "--dest-cols",
        default="1",
        help="Destination work-plate columns. Default: 1.",
    )
    parser.add_argument(
        "--p10-source-cols",
        default="1,2,3,4,5,6",
        help="p10 source 96DW columns to run. Default: 1,2,3,4,5,6.",
    )
    parser.add_argument(
        "--p50-source-cols",
        default="7",
        help="p50 source 96DW columns to run. Default: 7.",
    )
    parser.add_argument(
        "--discard-tips",
        action="store_true",
        help="Discard tips instead of returning. Use only for true wet/reagent runs.",
    )
    parser.add_argument(
        "--mix",
        action="store_true",
        help="Enable Mix after dispense. Default off for rhodamine placement/CV observation.",
    )
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        resources = await assign_deck(lh)

        dest_cols = parse_cols(args.dest_cols)
        p10_source_cols = parse_cols(args.p10_source_cols)
        p50_source_cols = parse_cols(args.p50_source_cols)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No tip pickup or liquid handling executed.")
        elif args.mode == "tips":
            await run_tip_test(lh, resources)
        elif args.mode == "p10":
            await run_p10_steps(
                lh,
                resources,
                source_cols=p10_source_cols,
                dest_cols=dest_cols,
                discard_tips=args.discard_tips,
                do_mix=args.mix,
            )
        elif args.mode == "p50":
            await run_p50_steps(
                lh,
                resources,
                source_cols=p50_source_cols,
                dest_cols=dest_cols,
                discard_tips=args.discard_tips,
                do_mix=args.mix,
            )
        elif args.mode == "rhodamine":
            await run_p10_steps(
                lh,
                resources,
                source_cols=p10_source_cols,
                dest_cols=dest_cols,
                discard_tips=args.discard_tips,
                do_mix=args.mix,
            )
            await run_p50_steps(
                lh,
                resources,
                source_cols=p50_source_cols,
                dest_cols=dest_cols,
                discard_tips=args.discard_tips,
                do_mix=args.mix,
            )

    finally:
        print("Stopping STAR backend...")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
