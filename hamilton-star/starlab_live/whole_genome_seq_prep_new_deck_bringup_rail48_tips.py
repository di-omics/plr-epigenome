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
from pylabrobot.liquid_handling.standard import Mix
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# -----------------------------------------------------------------------------
# WGS preparation (WGS preparation) - NEW DECK BRINGUP / BASIC MOVEMENTS
# Hamilton STAR + PyLabRobot on starpi.
#
# Safety posture:
# - Always uses lh.setup(skip_autoload=True).
# - Starts with deck assignment / tip pickup tests / elevated-height water moves.
# - No iSWAP, no autoload, no cleanup removals in this first bringup file.
# - Wet tests discard tips; dry tip pickup tests return tips.
#
# Active tip layout, updated after successful rail 48 p10/p1000 probing:
# - Rail 48 tip carrier:
#   pos0 = p10 filter
#   pos1 = p50 filter
#   pos2 = p300 filter slim
#   pos3 = p1000 filter
#
# Labware layout:
# - Rail 35 plate carrier:
#   pos0 = 96WP work plate
#   pos1 = magnetic 96WP position placeholder
#   pos2 = 96DW source plate
#   pos3 = 12-well reservoir
#   pos4 = magnetic 96WP position placeholder
# -----------------------------------------------------------------------------

# -----------------------------
# Deck constants
# -----------------------------
TIP_RAIL = 48

R48_P10_TIP_POS = 0
R48_P50_TIP_POS = 1
R48_P300_TIP_POS = 2
R48_P1000_TIP_POS = 3

LABWARE_RAIL = 35
WORK_96WP_POS = 0
MAG_96WP_POS_1 = 1
SOURCE_96DW_POS = 2
TROUGH_POS = 3
MAG_96WP_POS_2 = 4

DEST_COLUMNS = [1]  # Bringup default: A1:H1 only. Expand after validation.

# -----------------------------
# Conservative elevated geometry
# -----------------------------
# Positive X shifts the dispense position slightly right, matching prior working style.
DSP_X_RIGHT_SHIFT = 0.35

# Conservative/elevated 96WP dispense location. Tune down only after visual validation.
SAFE_96WP_DSP_HEIGHT = [18.0] * 8
SAFE_96WP_DSP_OFFSETS = [Coordinate(DSP_X_RIGHT_SHIFT, 2.45, 30.0)] * 8

# Conservative source 96DW aspirate locations.
P10_96DW_ASP_HEIGHT = [2.0] * 8
P10_96DW_ASP_OFFSETS = [Coordinate(0.20, 2.30, 0.0)] * 8
P50_96DW_ASP_HEIGHT = [2.0] * 8
P50_96DW_ASP_OFFSETS = [Coordinate(0.20, 2.30, 0.0)] * 8

# Trough geometry copied from prior p300 add/remove style, but used only for simple add tests here.
P300_TROUGH_ASP_HEIGHT = [0.0] * 8
P300_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, -24.0)] * 8
P1000_TROUGH_ASP_HEIGHT = [0.0] * 8
P1000_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, -24.0)] * 8

# Elevated plate dispense geometry for p300/p1000 into 96WP or magnetic 96WP position.
P300_96WP_DSP_HEIGHT = [18.0] * 8
P300_96WP_DSP_OFFSETS = [Coordinate(-0.60, 1.55, 30.0)] * 8
P1000_96WP_DSP_HEIGHT = [18.0] * 8
P1000_96WP_DSP_OFFSETS = [Coordinate(-0.60, 1.55, 30.0)] * 8

# Blowout tuning starts conservative. Increase in small increments only after droplet checks.
P10_BLOWOUT_AIR_VOLUME = 1.0
P50_BLOWOUT_AIR_VOLUME = 3.0
P300_BLOWOUT_AIR_VOLUME = 5.0
P1000_BLOWOUT_AIR_VOLUME = 5.0

MIX_REPETITIONS = 3
MIX_FLOW_RATE = 80

# -----------------------------
# WGS preparation source layout / volumes
# -----------------------------
# Source 96DW reagent columns are per-row A:H for 8-channel transfer.
SRC_LYSIS_COL = 1
SRC_REACTION_COL = 2
SRC_DNA_FRAGMENTATION_COL = 3
SRC_END_REPAIR_COL = 4
SRC_ADAPTER_COL = 5
SRC_LIGATION_MIX_COL = 6
SRC_LIBRARY_PCR_COL = 7

# Bulk reagents in 12-well trough.
TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"
TROUGH_WATER_TEST = "A5"

VOL_LYSIS = required_positive("wgs.stage_1_volume_ul")
VOL_REACTION = required_positive("wgs.stage_2_volume_ul")
VOL_DNA_FRAGMENTATION = required_positive("wgs.stage_3_volume_ul")
VOL_END_REPAIR = required_positive("wgs.stage_4_volume_ul")
VOL_ADAPTER = required_positive("wgs.stage_5_volume_ul")
VOL_LIGATION_MIX = required_positive("wgs.stage_6_volume_ul")
VOL_LIBRARY_PCR = required_positive("wgs.stage_7_volume_ul")

VOL_BEADS = required_positive("wgs.cleanup.bead_volume_ul")
VOL_ETOH = required_positive("wgs.cleanup.wash_add_ul")
VOL_ELUTION = required_positive("wgs.cleanup.elution_ul")

# Tip rack factory candidates.
P10_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_10uL_filter",
    "hamilton_96_tiprack_10ul_filter",
    "hamilton_96_tiprack_10uL_filter_slim",
    "hamilton_96_tiprack_10ul_filter_slim",
]
P50_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_50uL_filter",
    "hamilton_96_tiprack_50ul_filter",
]
P300_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_300uL_filter_slim",
    "hamilton_96_tiprack_300ul_filter_slim",
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
]
P1000_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_1000uL_filter",
    "hamilton_96_tiprack_1000ul_filter",
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


def make_p300_tiprack(name: str):
    return make_resource_from_candidates(
        "p300 filter slim tips",
        name,
        P300_TIP_FACTORY_CANDIDATES,
        nearby_terms=["tip", "300", "htf"],
    )


def make_p1000_tiprack(name: str):
    return make_resource_from_candidates(
        "p1000 filter tips",
        name,
        P1000_TIP_FACTORY_CANDIDATES,
        nearby_terms=["tip", "1000", "htf"],
    )


def make_96dw_source_plate(name: str):
    candidates = [
        "nest_96_wellplate_2mL_deep",
        "nest_96_wellplate_2mL_Vb",
        "Cor_96_wellplate_2mL_Vb",
        "Cor_96_wellplate_2mL_Ub",
        "Greiner_96_wellplate_2mL_Vb",
        "Axygen_96_wellplate_2mL_Vb",
    ]
    return make_resource_from_candidates(
        "96DW source plate",
        name,
        candidates,
        nearby_terms=["96", "deep", "2ml", "wellplate"],
    )


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


def mix_after_dispense(vol: float):
    mix_vol = max(1.0, min(float(vol), 20.0))
    return [Mix(volume=mix_vol, repetitions=MIX_REPETITIONS, flow_rate=MIX_FLOW_RATE)] * 8


def describe_resource(resource, label: str):
    print(f"{label}: name={resource.name}, location={resource.location}")


async def assign_new_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning NEW deck resources...")

    tip_carrier_48 = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")

    lh.deck.assign_child_resource(tip_carrier_48, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips_r48 = make_p10_tiprack(name="r48_p10_filter_tips")
    p50_tips_r48 = make_p50_tiprack(name="r48_p50_filter_tips")
    p300_tips_r48 = make_p300_tiprack(name="r48_p300_filter_slim_tips")
    p1000_tips_r48 = make_p1000_tiprack(name="r48_p1000_filter_tips")

    tip_carrier_48[R48_P10_TIP_POS] = p10_tips_r48
    tip_carrier_48[R48_P50_TIP_POS] = p50_tips_r48
    tip_carrier_48[R48_P300_TIP_POS] = p300_tips_r48
    tip_carrier_48[R48_P1000_TIP_POS] = p1000_tips_r48

    work_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_work_96wp")
    mag_96wp_1 = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_mag_96wp_placeholder")
    source_96dw = make_96dw_source_plate(name="rail35_pos2_source_96dw")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_12w_reservoir")
    mag_96wp_2 = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos4_mag_96wp_placeholder")

    # Note: the magnetic positions are modeled as 96WP placeholders for bringup.
    # If the magnetic adapter changes plate Z substantially, make a calibrated custom resource later.
    labware_carrier[WORK_96WP_POS] = work_96wp
    labware_carrier[MAG_96WP_POS_1] = mag_96wp_1
    labware_carrier[SOURCE_96DW_POS] = source_96dw
    labware_carrier[TROUGH_POS] = trough
    labware_carrier[MAG_96WP_POS_2] = mag_96wp_2

    resources = {
        "tip_carrier_48": tip_carrier_48,
        "labware_carrier": labware_carrier,
        "p10_tips_r48": p10_tips_r48,
        "p50_tips_r48": p50_tips_r48,
        "p300_tips_r48": p300_tips_r48,
        "p1000_tips_r48": p1000_tips_r48,
        "work_96wp": work_96wp,
        "mag_96wp_1": mag_96wp_1,
        "source_96dw": source_96dw,
        "trough": trough,
        "mag_96wp_2": mag_96wp_2,
    }

    print("\nDeck assignment complete. Resource locations:")
    for key, value in resources.items():
        if hasattr(value, "location"):
            describe_resource(value, key)

    return resources


async def pickup_return_test(lh: LiquidHandler, rack, label: str):
    print(f"\n=== TIP TEST: {label} A1:H1 pickup/return ===")
    await lh.pick_up_tips(rack["A1:H1"])
    await lh.return_tips()
    print(f"SUCCESS: {label} pickup/return completed.")


async def run_tip_tests(lh: LiquidHandler, r: Dict[str, object]):
    await pickup_return_test(lh, r["p10_tips_r48"], "rail48 pos0 p10 filter")
    await pickup_return_test(lh, r["p50_tips_r48"], "rail48 pos1 p50 filter")
    await pickup_return_test(lh, r["p300_tips_r48"], "rail48 pos2 p300 filter slim")
    await pickup_return_test(lh, r["p1000_tips_r48"], "rail48 pos3 p1000 filter")


async def transfer_column(
    lh: LiquidHandler,
    source_wells,
    target_wells,
    vol: float,
    asp_height: List[float],
    asp_offsets: List[Coordinate],
    dsp_height: List[float],
    dsp_offsets: List[Coordinate],
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

    print(f"Dispensing {vol} uL to destination at elevated 96WP height...")
    kwargs = {}
    if do_mix:
        kwargs["mix"] = mix_after_dispense(vol)
    await lh.dispense(
        target_wells,
        vols=vols,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[blowout_air_volume] * 8,
        **kwargs,
    )


async def transfer_from_trough(
    lh: LiquidHandler,
    source_well,
    target_wells,
    vol: float,
    asp_height: List[float],
    asp_offsets: List[Coordinate],
    dsp_height: List[float],
    dsp_offsets: List[Coordinate],
    blowout_air_volume: float,
    label: str,
    do_mix: bool = False,
):
    vols = [vol] * 8
    print(f"Aspirating {vol} uL x 8 from trough {label}...")
    await lh.aspirate(
        [source_well] * 8,
        vols=vols,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL x 8 to elevated 96WP destination...")
    kwargs = {}
    if do_mix:
        kwargs["mix"] = mix_after_dispense(vol)
    await lh.dispense(
        target_wells,
        vols=vols,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[blowout_air_volume] * 8,
        **kwargs,
    )


async def discard_tips_or_return(lh: LiquidHandler, wet: bool):
    if wet:
        print("Discarding wet tips...")
        try:
            await lh.discard_tips()
        except Exception as e:
            print(f"discard_tips failed ({e!r}); returning tips as fallback for dev run.")
            await lh.return_tips()
    else:
        print("Returning dry tips...")
        await lh.return_tips()


async def run_p10_water_test(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== P10 WATER TEST: source 96DW col1 -> rail35 pos0 work 96WP col1 ===")
    print("Load water/dye in source 96DW A1:H1. Destination is work 96WP A1:H1.")
    vol = 5.0
    await lh.pick_up_tips(r["p10_tips_r48"]["A1:H1"])
    try:
        await transfer_column(
            lh,
            r["source_96dw"]["A1:H1"],
            wells_for_column(r["work_96wp"], 1),
            vol,
            P10_96DW_ASP_HEIGHT,
            P10_96DW_ASP_OFFSETS,
            SAFE_96WP_DSP_HEIGHT,
            SAFE_96WP_DSP_OFFSETS,
            P10_BLOWOUT_AIR_VOLUME,
            "source 96DW col1 water/dye",
            do_mix=False,
        )
    finally:
        await discard_tips_or_return(lh, wet=True)
    print("SUCCESS: p10 elevated-height water test completed.")


async def run_p300_water_test(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== P300 WATER TEST: trough A5 -> rail35 pos0 work 96WP col2 ===")
    print("Load water/dye in trough A5. Destination is work 96WP A2:H2.")
    vol = 100.0
    await lh.pick_up_tips(r["p300_tips_r48"]["A1:H1"])
    try:
        await transfer_from_trough(
            lh,
            r["trough"][TROUGH_WATER_TEST][0],
            wells_for_column(r["work_96wp"], 2),
            vol,
            P300_TROUGH_ASP_HEIGHT,
            P300_TROUGH_ASP_OFFSETS,
            P300_96WP_DSP_HEIGHT,
            P300_96WP_DSP_OFFSETS,
            P300_BLOWOUT_AIR_VOLUME,
            f"{TROUGH_WATER_TEST} water/dye",
            do_mix=False,
        )
    finally:
        await discard_tips_or_return(lh, wet=True)
    print("SUCCESS: p300 elevated-height water test completed.")


async def run_whole_genome_seq_addition_scaffold(lh: LiquidHandler, r: Dict[str, object]):
    """First-pass liquid-addition scaffold only.

    This intentionally does not do iSWAP or bead-safe removals. It updates the
    old working liquid-handling logic to the new rail 35/48 deck layout.
    """
    source_96dw = r["source_96dw"]
    trough = r["trough"]
    work_plate = r["work_96wp"]
    cleanup_plate = r["mag_96wp_1"]

    print("\n=== WGS preparation ADDITION SCAFFOLD: small reagent additions with p10 ===")
    await lh.pick_up_tips(r["p10_tips_r48"]["A1:H1"])
    try:
        small_reagents = [
            (SRC_LYSIS_COL, VOL_LYSIS, "Lysis Mix"),
            (SRC_REACTION_COL, VOL_REACTION, "Reaction Mix"),
            (SRC_DNA_FRAGMENTATION_COL, VOL_DNA_FRAGMENTATION, "DNA fragmentation master mix"),
            (SRC_END_REPAIR_COL, VOL_END_REPAIR, "end-repair master mix"),
            (SRC_ADAPTER_COL, VOL_ADAPTER, "UDI Adapters - VERIFY MAP"),
            (SRC_LIGATION_MIX_COL, VOL_LIGATION_MIX, "ligation master mix"),
        ]
        for dest_col in DEST_COLUMNS:
            for src_col, vol, label in small_reagents:
                await transfer_column(
                    lh,
                    source_96dw[f"A{src_col}:H{src_col}"],
                    wells_for_column(work_plate, dest_col),
                    vol,
                    P10_96DW_ASP_HEIGHT,
                    P10_96DW_ASP_OFFSETS,
                    SAFE_96WP_DSP_HEIGHT,
                    SAFE_96WP_DSP_OFFSETS,
                    P10_BLOWOUT_AIR_VOLUME,
                    f"source 96DW column {src_col} ({label})",
                    do_mix=True,
                )
    finally:
        await discard_tips_or_return(lh, wet=True)

    print("\n=== WGS preparation ADDITION SCAFFOLD: operator-volume WGS stage with p50 ===")
    await lh.pick_up_tips(r["p50_tips_r48"]["A1:H1"])
    try:
        for dest_col in DEST_COLUMNS:
            await transfer_column(
                lh,
                source_96dw[f"A{SRC_LIBRARY_PCR_COL}:H{SRC_LIBRARY_PCR_COL}"],
                wells_for_column(work_plate, dest_col),
                VOL_LIBRARY_PCR,
                P50_96DW_ASP_HEIGHT,
                P50_96DW_ASP_OFFSETS,
                SAFE_96WP_DSP_HEIGHT,
                SAFE_96WP_DSP_OFFSETS,
                P50_BLOWOUT_AIR_VOLUME,
                f"source 96DW column {SRC_LIBRARY_PCR_COL} (library PCR master mix)",
                do_mix=True,
            )
    finally:
        await discard_tips_or_return(lh, wet=True)

    print("\n=== WGS preparation CLEANUP ADDITION SCAFFOLD: trough -> rail35 pos1 mag 96WP placeholder ===")
    await lh.pick_up_tips(r["p300_tips_r48"]["A1:H1"])
    try:
        cleanup_additions = [
            (TROUGH_BEADS, VOL_BEADS, "SPRI cleanup beads"),
            (TROUGH_ETOH1, VOL_ETOH, "80% EtOH wash 1"),
            (TROUGH_ETOH2, VOL_ETOH, "80% EtOH wash 2"),
            (TROUGH_ELUTION, VOL_ELUTION, "Elution Buffer"),
        ]
        for dest_col in DEST_COLUMNS:
            for trough_well, vol, label in cleanup_additions:
                await transfer_from_trough(
                    lh,
                    trough[trough_well][0],
                    wells_for_column(cleanup_plate, dest_col),
                    vol,
                    P300_TROUGH_ASP_HEIGHT,
                    P300_TROUGH_ASP_OFFSETS,
                    P300_96WP_DSP_HEIGHT,
                    P300_96WP_DSP_OFFSETS,
                    P300_BLOWOUT_AIR_VOLUME,
                    f"{trough_well} ({label})",
                    do_mix=False,
                )
    finally:
        await discard_tips_or_return(lh, wet=True)

    print("SUCCESS: WGS preparation new-deck addition scaffold completed.")
    print("NOTE: no cleanup removals, no residual ethanol removal, no final eluate transfer in this file.")


async def main():
    parser = argparse.ArgumentParser(description="STAR new-deck bringup for WGS preparation (WGS preparation) automation")
    parser.add_argument(
        "--mode",
        choices=["deck", "tips", "p10-water", "p300-water", "protocol-additions"],
        default="deck",
        help="Which bringup step to run. Start with deck, then tips, then water tests.",
    )
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_new_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No tip pickup or liquid handling executed.")
        elif args.mode == "tips":
            await run_tip_tests(lh, r)
        elif args.mode == "p10-water":
            await run_p10_water_test(lh, r)
        elif args.mode == "p300-water":
            await run_p300_water_test(lh, r)
        elif args.mode == "protocol-additions":
            await run_whole_genome_seq_addition_scaffold(lh, r)

    finally:
        print("Stopping STAR backend...")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
