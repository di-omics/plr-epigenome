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
from dataclasses import dataclass
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
# WGS preparation V2 P50-only 4-column camera run with TWO P50 TIP RACKS
#
# Why this variant exists:
# - Rhodamine B droplets were hanging from small tips / dry wells.
# - This uses P50 tips for all source-to-work volumes, including operator-supplied volumes.
# - P50 blowout is increased to 8 uL.
# - A 1 sec post-dispense dwell is added after every P50 dispense.
# - Recommended physical prep: prefill destination A1:H4 with ~50 uL water/buffer.
#
# Tip layout:
# - rail48 pos0 = P50 tips rack 1
# - rail48 pos1 = P50 tips rack 2
# - rail48 pos2 = P300 tips
#
# P50 tip cursor spans both P50 racks:
#   rack pos0 columns 1-12, then rack pos1 columns 1-12.
#
# For this 4-column run it will use:
#   P50 rack pos0 col 1 -> destination col 1, discard
#   P50 rack pos0 col 2 -> destination col 2, discard
#   P50 rack pos0 col 3 -> destination col 3, discard
#   P50 rack pos0 col 4 -> destination col 4, discard
#
# Full flow:
# 1. P50-only source-to-work into destination columns 1-4
# 2. iSWAP rail35 pos0 -> rail35 pos1 magnetic rack
# 3. P300 wash 1 add/remove with advancing discarded tips
# 4. P300 wash 2 add/remove with advancing discarded tips
# 5. iSWAP rail35 pos1 -> rail35 pos0
# -----------------------------------------------------------------------------

TIP_RAIL = 48
P50_TIP_POS_0 = 0
P50_TIP_POS_1 = 1
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

SOURCE_STEPS: List[Tuple[int, float, str]] = [
    (1, required_positive("wgs.stage_1_volume_ul"), "operator WGS stage 1"),
    (2, required_positive("wgs.stage_2_volume_ul"), "operator WGS stage 2"),
    (3, required_positive("wgs.stage_3_volume_ul"), "operator WGS stage 3"),
    (4, required_positive("wgs.stage_4_volume_ul"), "operator WGS stage 4"),
    (5, required_positive("wgs.stage_5_volume_ul"), "operator WGS stage 5"),
    (6, required_positive("wgs.stage_6_volume_ul"), "operator WGS stage 6"),
    (7, required_positive("wgs.stage_7_volume_ul"), "operator WGS stage 7"),
]

TROUGH_WASH1 = "A2"
TROUGH_WASH2 = "A3"
TROUGH_WASTE = "A12"

VOL_WASH = required_positive("wgs.cleanup.wash_add_ul")
VOL_REMOVE = required_positive("wgs.cleanup.wash_remove_ul")
WASH_INCUBATION_SECONDS = required_nonnegative("wgs.cleanup.wash_incubation_seconds")

# P50 source-to-work geometry.
P50_SOURCE_96DW_ASP_HEIGHT = [11.5] * 8
P50_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 5.20, 0.0)] * 8

WORK_96WP_DSP_HEIGHT = [8.0] * 8
WORK_96WP_DSP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8

P50_BLOWOUT_AIR_VOLUME = 8.0
POST_P50_DISPENSE_DWELL_SECONDS = 1.0

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


@dataclass
class MultiRackTipCursor:
    racks: List[object]
    name: str
    next_index: int = 0  # 0-based across all racks, 12 columns per rack.

    def take(self):
        rack_index = self.next_index // 12
        col = (self.next_index % 12) + 1
        if rack_index >= len(self.racks):
            raise RuntimeError(
                f"{self.name} tip cursor exhausted at global index {self.next_index + 1}; "
                f"loaded racks support {len(self.racks) * 12} tip columns."
            )
        self.next_index += 1
        print(
            f"Using {self.name} tip rack {rack_index + 1}/{len(self.racks)} column {col}; "
            f"next global {self.name} tip column will be {self.next_index + 1}."
        )
        return self.racks[rack_index][f"A{col}:H{col}"]


@dataclass
class SingleRackTipCursor:
    rack: object
    name: str
    next_col: int = 1

    def take(self):
        if self.next_col > 12:
            raise RuntimeError(f"{self.name} tip cursor exhausted at column {self.next_col}; max is 12.")
        col = self.next_col
        self.next_col += 1
        print(f"Using {self.name} tip column {col}; next {self.name} pickup will use column {self.next_col}.")
        return self.rack[f"A{col}:H{col}"]


def make_resource(label: str, name: str, candidates: List[str], terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)

    terms_lower = [term.lower() for term in terms]
    available = sorted(n for n in dir(plr_resources) if any(term in n.lower() for term in terms_lower))
    raise RuntimeError(f"Could not find factory for {label}. Tried {candidates}. Nearby: {available[:100]}")


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
    print("Assigning P50-only camera deck with TWO P50 TIP RACKS.")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p50_tips_0 = make_p50_tips("r48_pos0_p50_filter_tips")
    p50_tips_1 = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    source_96dw = make_96dw("rail35_pos2_source_96dw")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_12w_reservoir")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="wgs_work_96wp")

    tip_carrier[P50_TIP_POS_0] = p50_tips_0
    tip_carrier[P50_TIP_POS_1] = p50_tips_1
    tip_carrier[P300_TIP_POS] = p300_tips

    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_POS] = source_96dw
    labware_carrier[TROUGH_POS] = trough

    print("rail48 pos0=p50 tips rack 1, pos1=p50 tips rack 2, pos2=p300 tips")
    print("rail35 pos0=work plate, pos1=mag rack site, pos2=96DW source, pos3=reservoir")
    print(f"P50_SOURCE_96DW_ASP_OFFSETS = {P50_SOURCE_96DW_ASP_OFFSETS}")
    print(f"P50_BLOWOUT_AIR_VOLUME = {P50_BLOWOUT_AIR_VOLUME}")
    print(f"POST_P50_DISPENSE_DWELL_SECONDS = {POST_P50_DISPENSE_DWELL_SECONDS}")
    print(f"P300_MAG_DSP_OFFSETS = {P300_MAG_DSP_OFFSETS}")
    print(f"P300_MAG_REMOVE_ASP_OFFSETS = {P300_MAG_REMOVE_ASP_OFFSETS}")

    return {
        "labware_carrier": labware_carrier,
        "p50_tips_0": p50_tips_0,
        "p50_tips_1": p50_tips_1,
        "p300_tips": p300_tips,
        "source_96dw": source_96dw,
        "trough": trough,
        "work_plate": work_plate,
        "p50_cursor": MultiRackTipCursor([p50_tips_0, p50_tips_1], "p50"),
        "p300_cursor": SingleRackTipCursor(p300_tips, "p300"),
    }


async def discard_tips(lh: LiquidHandler):
    print("Discarding tips...")
    await lh.discard_tips()


async def transfer_p50(lh: LiquidHandler, r: Dict[str, object], src_col: int, dest_col: int, vol: float, label: str):
    vols = [vol] * 8
    print(f"Aspirating {vol} uL from source col {src_col} ({label}) -> work col {dest_col}...")
    await lh.aspirate(
        r["source_96dw"][f"A{src_col}:H{src_col}"],
        vols=vols,
        liquid_height=P50_SOURCE_96DW_ASP_HEIGHT,
        offsets=P50_SOURCE_96DW_ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )
    print(f"Dispensing {vol} uL to work col {dest_col} with p50 blowout {P50_BLOWOUT_AIR_VOLUME} uL...")
    await lh.dispense(
        wells_for_column(r["work_plate"], dest_col),
        vols=vols,
        liquid_height=WORK_96WP_DSP_HEIGHT,
        offsets=WORK_96WP_DSP_OFFSETS,
        blow_out_air_volume=[P50_BLOWOUT_AIR_VOLUME] * 8,
    )
    print(f"Post-dispense dwell {POST_P50_DISPENSE_DWELL_SECONDS} sec...")
    await asyncio.sleep(POST_P50_DISPENSE_DWELL_SECONDS)


async def run_source_to_work(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== P50-ONLY SOURCE-TO-WORK, DEST COLS 1-4 ===")
    for dest_col in DEST_COLS:
        print(f"\n--- p50 tip column for destination col {dest_col} ---")
        await lh.pick_up_tips(r["p50_cursor"].take())
        try:
            for src_col, vol, label in SOURCE_STEPS:
                await transfer_p50(lh, r, src_col, dest_col, vol, label)
        finally:
            await discard_tips(lh)
    print("SUCCESS: P50-only source-to-work completed.")


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


async def p300_add(lh: LiquidHandler, r: Dict[str, object], source_well: str):
    vols = [VOL_WASH] * 8
    print(f"\n=== P300 ADD {source_well} -> mag plate columns {DEST_COLS} ===")
    await lh.pick_up_tips(r["p300_cursor"].take())
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
        await discard_tips(lh)


async def p300_remove(lh: LiquidHandler, r: Dict[str, object]):
    vols = [VOL_REMOVE] * 8
    print(f"\n=== P300 REMOVE mag plate columns {DEST_COLS} -> waste {TROUGH_WASTE} ===")
    await lh.pick_up_tips(r["p300_cursor"].take())
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
        await discard_tips(lh)


async def run_washes(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== TWO WASH CYCLES ===")
    await p300_add(lh, r, TROUGH_WASH1)
    print(f"Incubating on magnet for {WASH_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(WASH_INCUBATION_SECONDS)
    await p300_remove(lh, r)

    await p300_add(lh, r, TROUGH_WASH2)
    print(f"Incubating on magnet for {WASH_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(WASH_INCUBATION_SECONDS)
    await p300_remove(lh, r)

    print("SUCCESS: wash cycles completed.")


async def main():
    parser = argparse.ArgumentParser(description="P50-only two-rack 4-column discard-tip camera protocol.")
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

        print("\n=== FULL P50-ONLY TWO-RACK 4-COLUMN DISCARD-TIP CAMERA RUN ===")
        print("Recommended: prefill destination A1:H4 with ~50 uL water/buffer before run.")
        await run_source_to_work(lh, r)
        await move_plate_pos0_to_pos1(lh, r)
        await run_washes(lh, r)
        await move_plate_pos1_to_pos0(lh, r)
        print("SUCCESS: full P50-only two-rack 4-column discard-tip camera run completed.")

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
