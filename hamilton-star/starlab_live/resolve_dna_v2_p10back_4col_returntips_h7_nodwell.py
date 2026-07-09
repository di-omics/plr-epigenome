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

# -----------------------------------------------------------------------------
# whole-genome sequencing V2 4-column P10-back / return-tips camera-debug run
#
# Purpose:
# - Bring p10 tips back for the small source-to-work volumes.
# - Keep the new droplet-release method:
#     destination prefill recommended: A1:H4 = ~50 uL water/buffer
#     destination dispense height lowered to 7.0
#     no post-dispense dwell
# - Do NOT discard tips. Return tips to rack after each block.
#
# Deck:
# - rail48 pos0 = p10 tips
# - rail48 pos1 = p50 tips
# - rail48 pos2 = p300 tips
# - rail35 pos0 = destination/work 96WP, starts here
# - rail35 pos1 = magnetic rack, empty/ready
# - rail35 pos2 = 96DW source plate
# - rail35 pos3 = 12-well reservoir
#
# Flow:
# 1. p10 source-to-work small-volume transfers into cols 1-4, return tips
# 2. p50 source-to-work 20 uL transfer into cols 1-4, return tips
# 3. iSWAP rail35 pos0 -> rail35 pos1 magnetic rack
# 4. p300 wash 1 add/remove, return tips
# 5. p300 wash 2 add/remove, return tips
# 6. iSWAP rail35 pos1 -> rail35 pos0
#
# This is a debugging/camera/RhB behavior test, not a contamination-safe
# production chemistry protocol.
# -----------------------------------------------------------------------------

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1
P300_TIP_POS = 2

LABWARE_RAIL = 35
WORK_POS = 0
MAG_POS = 1
SOURCE_POS = 2
TROUGH_POS = 3

DEST_COLS = [1, 2, 3, 4]

ISWAP_OFFSET_X_MM = 0.0
ISWAP_OFFSET_Y_MM = 3.5
ISWAP_POS0_PICKUP_Z_MM = 19.0
ISWAP_POS1_DROPOFF_Z_MM = 40.0
ISWAP_POS1_PICKUP_Z_MM = 42.0
ISWAP_POS0_DROPOFF_Z_MM = 20.0

P10_STEPS: List[Tuple[int, float, str]] = [
    (1, 3.0, "3 uL source"),
    (2, 6.0, "6 uL source"),
    (3, 3.0, "3 uL source"),
    (4, 4.0, "4 uL source"),
    (5, 5.0, "5 uL source"),
    (6, 5.0, "5 uL source"),
]
P50_STEPS: List[Tuple[int, float, str]] = [
    (7, 20.0, "20 uL source"),
]

TROUGH_WASH1 = "A2"
TROUGH_WASH2 = "A3"
TROUGH_WASTE = "A12"
VOL_WASH = 200.0
VOL_REMOVE = 180.0
WASH_INCUBATION_SECONDS = 30

# Tuned source aspirate geometry.
P10_SOURCE_96DW_ASP_HEIGHT = [13.0] * 8
P10_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 5.20, 0.0)] * 8

P50_SOURCE_96DW_ASP_HEIGHT = [11.5] * 8
P50_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 5.20, 0.0)] * 8

# New target-side droplet release geometry.
WORK_96WP_DSP_HEIGHT = [7.0] * 8
WORK_96WP_DSP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8

# Conservative p10 blowout bump. If p10 droplets still hang, try 3.0 next.
P10_BLOWOUT_AIR_VOLUME = 2.0

# Keep p50 strong for the 20 uL step.
P50_BLOWOUT_AIR_VOLUME = 6.0

# No dwell.
POST_DISPENSE_DWELL_SECONDS = 0.0

# P300 wash geometry.
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

P10_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_10uL_filter",
    "hamilton_96_tiprack_10ul_filter",
]
P50_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_50uL_filter",
    "hamilton_96_tiprack_50ul_filter",
]
P300_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
    "hamilton_96_tiprack_300uL_filter_slim",
    "hamilton_96_tiprack_300ul_filter_slim",
]
SOURCE_96DW_FACTORY_CANDIDATES = [
    "Cor_96_wellplate_2mL_Vb",
    "Cor_96_wellplate_2mL_Ub",
    "nest_96_wellplate_2mL_deep",
    "nest_96_wellplate_2mL_Vb",
    "Greiner_96_wellplate_2mL_Vb",
    "Axygen_96_wellplate_2mL_Vb",
]


def make_resource(label: str, name: str, candidates: List[str], terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)

    terms_lower = [term.lower() for term in terms]
    available = sorted(n for n in dir(plr_resources) if any(term in n.lower() for term in terms_lower))
    raise RuntimeError(f"Could not find factory for {label}. Tried {candidates}. Nearby: {available[:100]}")


def make_p10_tips(name: str):
    return make_resource("p10 filter tips", name, P10_TIP_FACTORY_CANDIDATES, ["tip", "10"])


def make_p50_tips(name: str):
    return make_resource("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES, ["tip", "50"])


def make_p300_tips(name: str):
    return make_resource("p300 filter tips", name, P300_TIP_FACTORY_CANDIDATES, ["tip", "300"])


def make_96dw(name: str):
    return make_resource("96DW source plate", name, SOURCE_96DW_FACTORY_CANDIDATES, ["96", "2ml", "deep"])


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


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


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning P10-back return-tip camera/debug deck.")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    source_96dw = make_96dw("rail35_pos2_source_96dw")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_12w_reservoir")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="resolve_work_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips

    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_POS] = source_96dw
    labware_carrier[TROUGH_POS] = trough

    print("rail48 pos0=p10 tips, pos1=p50 tips, pos2=p300 tips")
    print("rail35 pos0=work plate, pos1=mag rack site, pos2=96DW source, pos3=reservoir")
    print(f"WORK_96WP_DSP_HEIGHT = {WORK_96WP_DSP_HEIGHT}")
    print(f"P10_BLOWOUT_AIR_VOLUME = {P10_BLOWOUT_AIR_VOLUME}")
    print(f"P50_BLOWOUT_AIR_VOLUME = {P50_BLOWOUT_AIR_VOLUME}")
    print(f"POST_DISPENSE_DWELL_SECONDS = {POST_DISPENSE_DWELL_SECONDS}")
    print(f"P300_MAG_REMOVE_ASP_OFFSETS = {P300_MAG_REMOVE_ASP_OFFSETS}")

    return {
        "labware_carrier": labware_carrier,
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "p300_tips": p300_tips,
        "source_96dw": source_96dw,
        "trough": trough,
        "work_plate": work_plate,
    }


async def return_tips(lh: LiquidHandler):
    print("Returning tips to rack...")
    await lh.return_tips()


async def transfer(
    lh: LiquidHandler,
    r: Dict[str, object],
    src_col: int,
    dest_col: int,
    vol: float,
    asp_height: List[float],
    asp_offsets: List[Coordinate],
    blowout: float,
    label: str,
):
    vols = [vol] * 8
    print(f"Aspirating {vol} uL from source col {src_col} ({label}) -> work col {dest_col}...")
    await lh.aspirate(
        r["source_96dw"][f"A{src_col}:H{src_col}"],
        vols=vols,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )
    print(f"Dispensing {vol} uL to work col {dest_col} with blowout {blowout} uL...")
    await lh.dispense(
        wells_for_column(r["work_plate"], dest_col),
        vols=vols,
        liquid_height=WORK_96WP_DSP_HEIGHT,
        offsets=WORK_96WP_DSP_OFFSETS,
        blow_out_air_volume=[blowout] * 8,
    )
    if POST_DISPENSE_DWELL_SECONDS > 0:
        print(f"Post-dispense dwell {POST_DISPENSE_DWELL_SECONDS} sec...")
        await asyncio.sleep(POST_DISPENSE_DWELL_SECONDS)


async def run_source_to_work(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== SOURCE-TO-WORK: p10 small volumes back on p10 tips, return tips ===")

    print("\n--- p10 steps using rail48 pos0 tip col 1; return tips after block ---")
    await lh.pick_up_tips(r["p10_tips"]["A1:H1"])
    try:
        for dest_col in DEST_COLS:
            for src_col, vol, label in P10_STEPS:
                await transfer(
                    lh, r, src_col, dest_col, vol,
                    P10_SOURCE_96DW_ASP_HEIGHT,
                    P10_SOURCE_96DW_ASP_OFFSETS,
                    P10_BLOWOUT_AIR_VOLUME,
                    label,
                )
    finally:
        await return_tips(lh)

    print("\n--- p50 step using rail48 pos1 tip col 1; return tips after block ---")
    await lh.pick_up_tips(r["p50_tips"]["A1:H1"])
    try:
        for dest_col in DEST_COLS:
            for src_col, vol, label in P50_STEPS:
                await transfer(
                    lh, r, src_col, dest_col, vol,
                    P50_SOURCE_96DW_ASP_HEIGHT,
                    P50_SOURCE_96DW_ASP_OFFSETS,
                    P50_BLOWOUT_AIR_VOLUME,
                    label,
                )
    finally:
        await return_tips(lh)

    print("SUCCESS: source-to-work completed with return tips.")


async def move_plate_pos0_to_pos1(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== iSWAP rail35 pos0 -> pos1 ===")
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]

    print(f"Original plate pickup location: {work_plate.location}")
    apply_iswap_pos0_pickup_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")

    mag_site = carrier[MAG_POS]
    original_mag_location = Coordinate(mag_site.location.x, mag_site.location.y, mag_site.location.z)
    print(f"Original mag site location: {mag_site.location}")
    apply_iswap_pos1_dropoff_offset(mag_site)
    print(f"Offset mag dropoff location: {mag_site.location}")

    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, mag_site)

    mag_site.location = original_mag_location
    print("SUCCESS: iSWAP rail35 pos0 -> pos1 completed.")


async def move_plate_pos1_to_pos0(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== iSWAP rail35 pos1 -> pos0 ===")
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]

    print(f"Current plate pickup location before offset: {work_plate.location}")
    apply_iswap_pos1_pickup_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")

    work_site = carrier[WORK_POS]
    original_work_location = Coordinate(work_site.location.x, work_site.location.y, work_site.location.z)
    print(f"Original work site location: {work_site.location}")
    apply_iswap_pos0_dropoff_offset(work_site)
    print(f"Offset work dropoff location: {work_site.location}")

    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, work_site)

    work_site.location = original_work_location
    print("SUCCESS: iSWAP rail35 pos1 -> pos0 completed.")


async def p300_add(lh: LiquidHandler, r: Dict[str, object], source_well: str, tip_col: int):
    vols = [VOL_WASH] * 8
    print(f"\n=== P300 ADD {source_well} -> mag plate columns {DEST_COLS}; tip col {tip_col} ===")
    await lh.pick_up_tips(r["p300_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        for col in DEST_COLS:
            print(f"Aspirating {VOL_WASH} uL x8 from reservoir {source_well}...")
            await lh.aspirate(
                [r["trough"][source_well][0]] * 8,
                vols=vols,
                liquid_height=P300_TROUGH_ASP_HEIGHT,
                offsets=P300_TROUGH_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )
            print(f"Dispensing {VOL_WASH} uL x8 to mag plate column {col}...")
            await lh.dispense(
                wells_for_column(r["work_plate"], col),
                vols=vols,
                liquid_height=P300_MAG_DSP_HEIGHT,
                offsets=P300_MAG_DSP_OFFSETS,
                blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8,
            )
    finally:
        await return_tips(lh)


async def p300_remove(lh: LiquidHandler, r: Dict[str, object], tip_col: int):
    vols = [VOL_REMOVE] * 8
    print(f"\n=== P300 REMOVE mag plate columns {DEST_COLS} -> waste {TROUGH_WASTE}; tip col {tip_col} ===")
    await lh.pick_up_tips(r["p300_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        for col in DEST_COLS:
            print(f"Aspirating {VOL_REMOVE} uL x8 from mag plate column {col}...")
            await lh.aspirate(
                wells_for_column(r["work_plate"], col),
                vols=vols,
                liquid_height=P300_MAG_REMOVE_ASP_HEIGHT,
                offsets=P300_MAG_REMOVE_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )
            print(f"Dispensing {VOL_REMOVE} uL x8 to reservoir waste {TROUGH_WASTE}...")
            await lh.dispense(
                [r["trough"][TROUGH_WASTE][0]] * 8,
                vols=vols,
                liquid_height=P300_WASTE_DSP_HEIGHT,
                offsets=P300_WASTE_DSP_OFFSETS,
                blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8,
            )
    finally:
        await return_tips(lh)


async def run_washes(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== TWO WASH CYCLES, return p300 tips ===")
    await p300_add(lh, r, TROUGH_WASH1, tip_col=1)
    print(f"Incubating on magnet for {WASH_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(WASH_INCUBATION_SECONDS)
    await p300_remove(lh, r, tip_col=2)

    await p300_add(lh, r, TROUGH_WASH2, tip_col=3)
    print(f"Incubating on magnet for {WASH_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(WASH_INCUBATION_SECONDS)
    await p300_remove(lh, r, tip_col=4)

    print("SUCCESS: wash cycles completed.")


async def main():
    parser = argparse.ArgumentParser(description="P10-back 4-column return-tip camera/debug protocol.")
    parser.add_argument("--mode", choices=["deck", "run"], default="run")
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("Mode deck: assignment only. No movement or liquid handling executed.")
            return

        print("\n=== FULL P10-BACK 4-COLUMN RETURN-TIP CAMERA/DEBUG RUN ===")
        print("Recommended: prefill destination A1:H4 with ~50 uL water/buffer before run.")
        await run_source_to_work(lh, r)
        await move_plate_pos0_to_pos1(lh, r)
        await run_washes(lh, r)
        await move_plate_pos1_to_pos0(lh, r)
        print("SUCCESS: full P10-back 4-column return-tip camera/debug run completed.")

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
