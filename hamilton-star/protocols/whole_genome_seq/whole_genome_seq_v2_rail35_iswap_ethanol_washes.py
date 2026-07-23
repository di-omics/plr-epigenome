import argparse
import asyncio
from typing import Dict, List, Tuple

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

# WGS preparation (PTA) Automation - V2 rail35 integrated scaffold
# Integrates:
# - p10/p50 source 96DW -> work 96WP source-to-work additions.
# - iSWAP move: rail35 pos0 work plate -> rail35 pos1 magnetic rack position.
# - p300 ethanol wash add/remove cycle on rail35 pos1 magnetic rack.
# - iSWAP return: rail35 pos1 -> rail35 pos0.
#
# Current deck:
# - rail48 pos0 = p10 filter tips
# - rail48 pos1 = p50 filter tips
# - rail48 pos2 = p300 filter conductive tips; NEST 345112 works with non-slim 300uL factory
# - rail48 pos3 = p1000 filter tips, reserved
# - rail35 pos0 = work 96WP / protocol starting position
# - rail35 pos1 = magnetic rack / bead-clean position
# - rail35 pos2 = 96DW source plate
# - rail35 pos3 = 12-well reservoir
#
# Safety/testing:
# - Uses lh.setup(skip_autoload=True).
# - Tips return by default.
# - Pass --discard-tips only for true wet/reagent runs.
# - Test --mode iswap alone before --mode iswap-ethanol-return or --mode full-v2.

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1
P300_TIP_POS = 2
P1000_TIP_POS = 3

LABWARE_RAIL = 35
WORK_POS = 0
MAG_POS = 1
SOURCE_96DW_POS = 2
TROUGH_POS = 3

DEST_COLUMNS = [1]

# Previous verified iSWAP offsets. Apply only to pickup/dropoff targets, then restore site locations.
ISWAP_OFFSET_X_MM = 0.0
ISWAP_OFFSET_Y_MM = 3.5

# Directional iSWAP Z offsets tuned on rail35.
# pos0 -> pos1:
# - pos0 pickup needed the tiniest lower than 20.0.
# - pos1 magnetic rack dropoff was good at 40.0.
# pos1 -> pos0:
# - pos1 pickup needed a bit higher than pos0 pickup.
# - pos0 dropoff was too high/flying at 40.0, so lower it.
ISWAP_POS0_PICKUP_Z_MM = 19.0
ISWAP_POS1_DROPOFF_Z_MM = 40.0
ISWAP_POS1_PICKUP_Z_MM = 42.0
ISWAP_POS0_DROPOFF_Z_MM = 20.0

# 96DW source reagent layout.
SRC_LYSIS_COL = 1
SRC_REACTION_COL = 2
SRC_DNAPREP_COL = 3
SRC_FERAT_COL = 4
SRC_ADAPTER_COL = 5
SRC_LP2L_COL = 6
SRC_LIBAMP_COL = 7

P10_STEPS: List[Tuple[int, float, str]] = [
    (SRC_LYSIS_COL, 3.0, "Lysis Mix"),
    (SRC_REACTION_COL, 6.0, "Reaction Mix"),
    (SRC_DNAPREP_COL, 3.0, "DNA Prep Master Mix"),
    (SRC_FERAT_COL, 4.0, "FERAT Master Mix"),
    (SRC_ADAPTER_COL, 5.0, "UDI Adapters - VERIFY MAP"),
    (SRC_LP2L_COL, 5.0, "LP2L"),
]
P50_STEPS: List[Tuple[int, float, str]] = [
    (SRC_LIBAMP_COL, 20.0, "Amplification Master Mix"),
]

# Reservoir layout.
TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"
TROUGH_WATER_TEST = "A5"
TROUGH_WASTE = "A12"

VOL_ETOH = 200.0
VOL_ETOH_REMOVE = 180.0
ETHANOL_INCUBATION_SECONDS = 30

# p10/p50 source-to-work geometry.
P10_SOURCE_96DW_ASP_HEIGHT = [13.0] * 8
P10_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 5.20, 0.0)] * 8
P50_SOURCE_96DW_ASP_HEIGHT = [11.5] * 8
P50_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 5.20, 0.0)] * 8
WORK_96WP_DSP_HEIGHT = [16.0] * 8
WORK_96WP_DSP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8
P10_BLOWOUT_AIR_VOLUME = 1.0
P50_BLOWOUT_AIR_VOLUME = 2.0

# p300 ethanol wash geometry, tuned on rail35 pos1 magnetic rack.
P300_TROUGH_ASP_HEIGHT = [10.0] * 8
P300_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P300_MAG_DSP_HEIGHT = [13.0] * 8
P300_MAG_DSP_OFFSETS = [Coordinate(-0.60, 2.20, 23.0)] * 8
P300_MAG_REMOVE_ASP_HEIGHT = [32.0] * 8
P300_MAG_REMOVE_ASP_OFFSETS = [Coordinate(-0.60, 3.35, 0.0)] * 8
P300_WASTE_DSP_HEIGHT = [12.0] * 8
P300_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P300_ADD_BLOWOUT_AIR_VOLUME = 3.0
P300_REMOVE_BLOWOUT_AIR_VOLUME = 2.0

P10_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_10uL_filter", "hamilton_96_tiprack_10ul_filter"]
P50_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_50uL_filter", "hamilton_96_tiprack_50ul_filter"]
P300_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
    "hamilton_96_tiprack_300uL_filter_slim",
    "hamilton_96_tiprack_300ul_filter_slim",
]
P1000_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_1000uL_filter", "hamilton_96_tiprack_1000ul_filter"]
SOURCE_96DW_FACTORY_CANDIDATES = [
    "Cor_96_wellplate_2mL_Vb",
    "Cor_96_wellplate_2mL_Ub",
    "nest_96_wellplate_2mL_deep",
    "nest_96_wellplate_2mL_Vb",
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
    available = sorted(n for n in dir(plr_resources) if any(term in n.lower() for term in terms))
    raise RuntimeError(f"Could not find resource factory for {label}. Tried {candidates}. Nearby: {available[:160]}")


def make_p10_tiprack(name: str):
    return make_resource_from_candidates("p10 filter tips", name, P10_TIP_FACTORY_CANDIDATES, ["tip", "10"])


def make_p50_tiprack(name: str):
    return make_resource_from_candidates("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES, ["tip", "50"])


def make_p300_tiprack(name: str):
    return make_resource_from_candidates("p300 filter tips", name, P300_TIP_FACTORY_CANDIDATES, ["tip", "300"])


def make_p1000_tiprack(name: str):
    return make_resource_from_candidates("p1000 filter tips", name, P1000_TIP_FACTORY_CANDIDATES, ["tip", "1000"])


def make_96dw_source_plate(name: str):
    return make_resource_from_candidates("96DW source plate", name, SOURCE_96DW_FACTORY_CANDIDATES, ["96", "2ml", "deep"])


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


def tips_for_column(rack, col: int):
    return rack[f"A{col}:H{col}"]


def parse_cols(s: str) -> List[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def offset_location(resource, dx=0.0, dy=0.0, dz=0.0):
    loc = resource.location
    if loc is None:
        raise RuntimeError(f"{resource.name} has no location.")
    resource.location = Coordinate(loc.x + dx, loc.y + dy, loc.z + dz)


def apply_iswap_pos0_pickup_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS0_PICKUP_Z_MM)


def apply_iswap_pos1_dropoff_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS1_DROPOFF_Z_MM)


def apply_iswap_pos1_pickup_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS1_PICKUP_Z_MM)


def apply_iswap_pos0_dropoff_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS0_DROPOFF_Z_MM)


async def assign_deck(lh: LiquidHandler, plate_start: str = "work") -> Dict[str, object]:
    print("Assigning WGS preparation V2 rail35 deck resources...")
    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tiprack("r48_p10_filter_tips")
    p50_tips = make_p50_tiprack("r48_p50_filter_tips")
    p300_tips = make_p300_tiprack("r48_p300_filter_tips")
    p1000_tips = make_p1000_tiprack("r48_p1000_filter_tips")
    source_96dw = make_96dw_source_plate("rail35_pos2_source_96dw")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_12w_reservoir")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="resolve_work_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips
    tip_carrier[P1000_TIP_POS] = p1000_tips

    if plate_start == "work":
        labware_carrier[WORK_POS] = work_plate
    elif plate_start == "mag":
        labware_carrier[MAG_POS] = work_plate
    else:
        raise ValueError("plate_start must be 'work' or 'mag'")
    labware_carrier[SOURCE_96DW_POS] = source_96dw
    labware_carrier[TROUGH_POS] = trough

    print("\nAssigned resources:")
    print(f"tip_carrier: {tip_carrier.location}")
    print(f"labware_carrier: {labware_carrier.location}")
    print("plate_start: rail35 pos0 work" if plate_start == "work" else "plate_start: rail35 pos1 mag")
    print(f"work_plate: {work_plate.location}")
    print(f"source_96dw: {source_96dw.location}")
    print(f"trough: {trough.location}")
    print("\nKey V2 geometry:")
    print(f"P10_SOURCE_96DW_ASP_HEIGHT = {P10_SOURCE_96DW_ASP_HEIGHT}")
    print(f"P10_SOURCE_96DW_ASP_OFFSETS = {P10_SOURCE_96DW_ASP_OFFSETS}")
    print(f"P50_SOURCE_96DW_ASP_HEIGHT = {P50_SOURCE_96DW_ASP_HEIGHT}")
    print(f"P50_SOURCE_96DW_ASP_OFFSETS = {P50_SOURCE_96DW_ASP_OFFSETS}")
    print(f"WORK_96WP_DSP_HEIGHT = {WORK_96WP_DSP_HEIGHT}")
    print(f"WORK_96WP_DSP_OFFSETS = {WORK_96WP_DSP_OFFSETS}")
    print(f"P300_TROUGH_ASP_HEIGHT = {P300_TROUGH_ASP_HEIGHT}")
    print(f"P300_MAG_DSP_HEIGHT = {P300_MAG_DSP_HEIGHT}")
    print(f"P300_MAG_DSP_OFFSETS = {P300_MAG_DSP_OFFSETS}")
    print(f"P300_MAG_REMOVE_ASP_HEIGHT = {P300_MAG_REMOVE_ASP_HEIGHT}")
    print(f"P300_MAG_REMOVE_ASP_OFFSETS = {P300_MAG_REMOVE_ASP_OFFSETS}")
    print(f"ISWAP X/Y pos0_pickup/pos1_dropoff/pos1_pickup/pos0_dropoff = {ISWAP_OFFSET_X_MM}, {ISWAP_OFFSET_Y_MM}, {ISWAP_POS0_PICKUP_Z_MM}, {ISWAP_POS1_DROPOFF_Z_MM}, {ISWAP_POS1_PICKUP_Z_MM}, {ISWAP_POS0_DROPOFF_Z_MM}")

    return {
        "labware_carrier": labware_carrier,
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "p300_tips": p300_tips,
        "p1000_tips": p1000_tips,
        "work_plate": work_plate,
        "source_96dw": source_96dw,
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


async def transfer_column(lh, source_wells, target_wells, vol, asp_height, asp_offsets, dsp_height, dsp_offsets, blowout_air_volume, label):
    vols = [vol] * 8
    print(f"Aspirating {vol} uL from {label}...")
    await lh.aspirate(source_wells, vols=vols, liquid_height=asp_height, offsets=asp_offsets, blow_out_air_volume=[0.0] * 8)
    print(f"Dispensing {vol} uL to work plate...")
    await lh.dispense(target_wells, vols=vols, liquid_height=dsp_height, offsets=dsp_offsets, blow_out_air_volume=[blowout_air_volume] * 8)


async def run_p10_p50_source_to_work(lh, r, dest_cols, discard_tips):
    print("\n=== V2 SOURCE-TO-WORK: p10/p50 96DW rail35 pos2 -> work plate rail35 pos0 ===")
    print("\n--- p10 source-to-work steps ---")
    await lh.pick_up_tips(tips_for_column(r["p10_tips"], 1))
    try:
        for dest_col in dest_cols:
            for src_col, vol, label in P10_STEPS:
                await transfer_column(
                    lh,
                    r["source_96dw"][f"A{src_col}:H{src_col}"],
                    wells_for_column(r["work_plate"], dest_col),
                    vol,
                    P10_SOURCE_96DW_ASP_HEIGHT,
                    P10_SOURCE_96DW_ASP_OFFSETS,
                    WORK_96WP_DSP_HEIGHT,
                    WORK_96WP_DSP_OFFSETS,
                    P10_BLOWOUT_AIR_VOLUME,
                    f"source 96DW col {src_col} ({label}) -> work col {dest_col}",
                )
    finally:
        await finish_tips(lh, discard_tips)

    print("\n--- p50 source-to-work steps ---")
    await lh.pick_up_tips(tips_for_column(r["p50_tips"], 1))
    try:
        for dest_col in dest_cols:
            for src_col, vol, label in P50_STEPS:
                await transfer_column(
                    lh,
                    r["source_96dw"][f"A{src_col}:H{src_col}"],
                    wells_for_column(r["work_plate"], dest_col),
                    vol,
                    P50_SOURCE_96DW_ASP_HEIGHT,
                    P50_SOURCE_96DW_ASP_OFFSETS,
                    WORK_96WP_DSP_HEIGHT,
                    WORK_96WP_DSP_OFFSETS,
                    P50_BLOWOUT_AIR_VOLUME,
                    f"source 96DW col {src_col} ({label}) -> work col {dest_col}",
                )
    finally:
        await finish_tips(lh, discard_tips)
    print("SUCCESS: p10/p50 source-to-work completed.")


async def move_plate_pos0_to_pos1(lh, r):
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]
    print("\n=== iSWAP MOVE: rail35 pos0 -> rail35 pos1 magnetic rack ===")
    print(f"Using iSWAP pos0->pos1 offsets X={ISWAP_OFFSET_X_MM}, Y={ISWAP_OFFSET_Y_MM}, pickupZ={ISWAP_POS0_PICKUP_Z_MM}, dropoffZ={ISWAP_POS1_DROPOFF_Z_MM} mm")
    print(f"Original plate pickup location: {work_plate.location}")
    apply_iswap_pos0_pickup_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")
    mag_site = carrier[MAG_POS]
    original_mag_site_location = Coordinate(mag_site.location.x, mag_site.location.y, mag_site.location.z)
    print(f"Original mag site location: {mag_site.location}")
    apply_iswap_pos1_dropoff_offset(mag_site)
    print(f"Offset mag dropoff location: {mag_site.location}")
    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, mag_site)
    mag_site.location = original_mag_site_location
    print(f"Restored rail35 pos1 mag site location for LH: {mag_site.location}")
    print("SUCCESS: iSWAP rail35 pos0 -> pos1 completed.")


async def move_plate_pos1_to_pos0(lh, r):
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]
    print("\n=== iSWAP MOVE: rail35 pos1 magnetic rack -> rail35 pos0 ===")
    print(f"Using iSWAP pos1->pos0 offsets X={ISWAP_OFFSET_X_MM}, Y={ISWAP_OFFSET_Y_MM}, pickupZ={ISWAP_POS1_PICKUP_Z_MM}, dropoffZ={ISWAP_POS0_DROPOFF_Z_MM} mm")
    print(f"Current plate pickup location before offset: {work_plate.location}")
    apply_iswap_pos1_pickup_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")
    work_site = carrier[WORK_POS]
    original_work_site_location = Coordinate(work_site.location.x, work_site.location.y, work_site.location.z)
    print(f"Original work site location: {work_site.location}")
    apply_iswap_pos0_dropoff_offset(work_site)
    print(f"Offset work dropoff location: {work_site.location}")
    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, work_site)
    work_site.location = original_work_site_location
    print(f"Restored rail35 pos0 work site location: {work_site.location}")
    print("SUCCESS: iSWAP rail35 pos1 -> pos0 completed.")


async def p300_add_from_reservoir_to_mag(lh, r, source_well_name, target_cols, vol, tip_col, discard_tips):
    vols = [vol] * 8
    trough = r["trough"]
    plate = r["work_plate"]
    print(f"\n=== P300 ADD: reservoir {source_well_name} -> mag plate columns {target_cols}, {vol} uL ===")
    await lh.pick_up_tips(tips_for_column(r["p300_tips"], tip_col))
    try:
        for col in target_cols:
            print(f"Aspirating {vol} uL x8 from reservoir {source_well_name}...")
            await lh.aspirate([trough[source_well_name][0]] * 8, vols=vols, liquid_height=P300_TROUGH_ASP_HEIGHT, offsets=P300_TROUGH_ASP_OFFSETS, blow_out_air_volume=[0.0] * 8)
            print(f"Dispensing {vol} uL x8 to mag plate column {col}...")
            await lh.dispense(wells_for_column(plate, col), vols=vols, liquid_height=P300_MAG_DSP_HEIGHT, offsets=P300_MAG_DSP_OFFSETS, blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8)
    finally:
        await finish_tips(lh, discard_tips)


async def p300_remove_from_mag_to_waste(lh, r, source_cols, waste_well_name, vol, tip_col, discard_tips):
    vols = [vol] * 8
    trough = r["trough"]
    plate = r["work_plate"]
    print(f"\n=== P300 REMOVE: mag plate columns {source_cols} -> waste {waste_well_name}, {vol} uL ===")
    await lh.pick_up_tips(tips_for_column(r["p300_tips"], tip_col))
    try:
        for col in source_cols:
            print(f"Aspirating {vol} uL x8 from mag plate column {col}...")
            await lh.aspirate(wells_for_column(plate, col), vols=vols, liquid_height=P300_MAG_REMOVE_ASP_HEIGHT, offsets=P300_MAG_REMOVE_ASP_OFFSETS, blow_out_air_volume=[0.0] * 8)
            print(f"Dispensing {vol} uL x8 to reservoir waste {waste_well_name}...")
            await lh.dispense([trough[waste_well_name][0]] * 8, vols=vols, liquid_height=P300_WASTE_DSP_HEIGHT, offsets=P300_WASTE_DSP_OFFSETS, blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8)
    finally:
        await finish_tips(lh, discard_tips)


async def run_two_ethanol_washes(lh, r, dest_cols, discard_tips):
    print("\n=== V2 ETHANOL WASHES ON MAGNET: two 200 uL washes with 30 sec incubations ===")
    await p300_add_from_reservoir_to_mag(lh, r, TROUGH_ETOH1, dest_cols, VOL_ETOH, tip_col=1, discard_tips=discard_tips)
    print(f"Incubating on magnet for {ETHANOL_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(ETHANOL_INCUBATION_SECONDS)
    await p300_remove_from_mag_to_waste(lh, r, dest_cols, TROUGH_WASTE, VOL_ETOH_REMOVE, tip_col=2, discard_tips=discard_tips)
    await p300_add_from_reservoir_to_mag(lh, r, TROUGH_ETOH2, dest_cols, VOL_ETOH, tip_col=3, discard_tips=discard_tips)
    print(f"Incubating on magnet for {ETHANOL_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(ETHANOL_INCUBATION_SECONDS)
    await p300_remove_from_mag_to_waste(lh, r, dest_cols, TROUGH_WASTE, VOL_ETOH_REMOVE, tip_col=4, discard_tips=discard_tips)
    print("SUCCESS: two ethanol washes completed.")


async def main():
    parser = argparse.ArgumentParser(description="WGS preparation V2 rail35 p10/p50 + iSWAP + p300 ethanol wash scaffold.")
    parser.add_argument("--mode", choices=["deck", "rhodamine", "iswap", "iswap-return", "ethanol-washes", "iswap-ethanol-return", "full-v2"], default="deck")
    parser.add_argument("--dest-cols", default="1")
    parser.add_argument("--discard-tips", action="store_true")
    args = parser.parse_args()

    dest_cols = parse_cols(args.dest_cols)
    plate_start = "mag" if args.mode == "ethanol-washes" else "work"

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)
    try:
        resources = await assign_deck(lh, plate_start=plate_start)
        if args.mode == "deck":
            print("\nMode deck: assignment only. No movement or liquid handling executed.")
        elif args.mode == "rhodamine":
            await run_p10_p50_source_to_work(lh, resources, dest_cols, args.discard_tips)
        elif args.mode == "iswap":
            await move_plate_pos0_to_pos1(lh, resources)
        elif args.mode == "iswap-return":
            await move_plate_pos0_to_pos1(lh, resources)
            await move_plate_pos1_to_pos0(lh, resources)
        elif args.mode == "ethanol-washes":
            await run_two_ethanol_washes(lh, resources, dest_cols, args.discard_tips)
        elif args.mode == "iswap-ethanol-return":
            await move_plate_pos0_to_pos1(lh, resources)
            await run_two_ethanol_washes(lh, resources, dest_cols, args.discard_tips)
            await move_plate_pos1_to_pos0(lh, resources)
        elif args.mode == "full-v2":
            await run_p10_p50_source_to_work(lh, resources, dest_cols, args.discard_tips)
            await move_plate_pos0_to_pos1(lh, resources)
            await run_two_ethanol_washes(lh, resources, dest_cols, args.discard_tips)
            await move_plate_pos1_to_pos0(lh, resources)
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
