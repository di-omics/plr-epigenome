# DEFAULT CAMERA RUN VERSION
# Running this file with no arguments executes:
#   --mode full-v2 --dest-cols 1,2,3,4 --discard-tips
#
# It uses TipCursor objects so each pickup advances to the next tip column
# and then discards tips. It does not return tips to the same slots.
#
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

# WGS preparation V2 production-style scaffold with explicit tip-column advancement.
# Same tuned rail35 geometry/iSWAP/ethanol logic as the working V2.
#
# Deck:
# rail48 pos0 p10 tips, pos1 p50 tips, pos2 p300 tips, pos3 p1000 reserved
# rail35 pos0 work 96WP, pos1 magnetic rack, pos2 96DW source, pos3 reservoir
#
# Modes:
#   deck
#   rhodamine-4      p10/p50 source-to-work only, default dest cols 1-4
#   source-to-work   p10/p50 source-to-work only, user --dest-cols
#   full-v2          source-to-work + iSWAP + two ethanol washes + iSWAP return
#
# Tip behavior:
#   default: return tips for geometry/stress tests
#   --discard-tips: advance to next tip column every pickup
#   --fresh-tips-per-reagent: one fresh p10/p50 tip column per reagent per destination
#       limited to <=2 dest columns for p10 with one rack because 6 p10 reagents/col

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

ISWAP_OFFSET_X_MM = 0.0
ISWAP_OFFSET_Y_MM = 3.5
ISWAP_POS0_PICKUP_Z_MM = 19.0
ISWAP_POS1_DROPOFF_Z_MM = 40.0
ISWAP_POS1_PICKUP_Z_MM = 42.0
ISWAP_POS0_DROPOFF_Z_MM = 20.0

P10_STEPS: List[Tuple[int, float, str]] = [
    (1, 3.0, "Lysis Mix"),
    (2, 6.0, "Reaction Mix"),
    (3, 3.0, "DNA Prep Master Mix"),
    (4, 4.0, "FERAT Master Mix"),
    (5, 5.0, "UDI Adapters - VERIFY MAP"),
    (6, 5.0, "LP2L"),
]
P50_STEPS: List[Tuple[int, float, str]] = [(7, 20.0, "Amplification Master Mix")]

TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_WASTE = "A12"
VOL_ETOH = 200.0
VOL_ETOH_REMOVE = 180.0
ETHANOL_INCUBATION_SECONDS = 30

P10_SOURCE_96DW_ASP_HEIGHT = [13.0] * 8
P10_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 5.20, 0.0)] * 8
P50_SOURCE_96DW_ASP_HEIGHT = [11.5] * 8
P50_SOURCE_96DW_ASP_OFFSETS = [Coordinate(0.35, 5.20, 0.0)] * 8

WORK_96WP_DSP_HEIGHT = [16.0] * 8
WORK_96WP_DSP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8
P10_BLOWOUT_AIR_VOLUME = 1.0
P50_BLOWOUT_AIR_VOLUME = 2.0

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


@dataclass
class TipCursor:
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


def make_resource_from_candidates(label: str, name: str, candidates: List[str], nearby_terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)
    terms = [t.lower() for t in nearby_terms]
    available = sorted(n for n in dir(plr_resources) if any(t in n.lower() for t in terms))
    raise RuntimeError(f"No resource factory for {label}. Tried {candidates}. Nearby: {available[:120]}")


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


def parse_cols(s: str) -> List[int]:
    cols = [int(x.strip()) for x in s.split(",") if x.strip()]
    if not cols or min(cols) < 1 or max(cols) > 12:
        raise ValueError("Destination columns must be 1-12.")
    return cols


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
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96DW_POS] = source_96dw
    labware_carrier[TROUGH_POS] = trough

    print("Assigned deck: rail35 pos0 work, pos1 mag, pos2 96DW, pos3 reservoir; rail48 pos0/1/2 p10/p50/p300.")
    print(f"P10_SOURCE_96DW_ASP_OFFSETS = {P10_SOURCE_96DW_ASP_OFFSETS}")
    print(f"P50_SOURCE_96DW_ASP_OFFSETS = {P50_SOURCE_96DW_ASP_OFFSETS}")
    print(f"P300_MAG_DSP_OFFSETS = {P300_MAG_DSP_OFFSETS}")
    print(f"P300_MAG_REMOVE_ASP_HEIGHT = {P300_MAG_REMOVE_ASP_HEIGHT}")
    print(f"P300_MAG_REMOVE_ASP_OFFSETS = {P300_MAG_REMOVE_ASP_OFFSETS}")
    print(f"P300_WASTE_DSP_HEIGHT = {P300_WASTE_DSP_HEIGHT}")
    print(f"ISWAP Z pos0 pickup/pos1 dropoff/pos1 pickup/pos0 dropoff = "
          f"{ISWAP_POS0_PICKUP_Z_MM}, {ISWAP_POS1_DROPOFF_Z_MM}, {ISWAP_POS1_PICKUP_Z_MM}, {ISWAP_POS0_DROPOFF_Z_MM}")

    return {
        "labware_carrier": labware_carrier,
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "p300_tips": p300_tips,
        "source_96dw": source_96dw,
        "trough": trough,
        "work_plate": work_plate,
        "p10_cursor": TipCursor(p10_tips, "p10"),
        "p50_cursor": TipCursor(p50_tips, "p50"),
        "p300_cursor": TipCursor(p300_tips, "p300"),
    }


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips.")
        await lh.discard_tips()
    else:
        print("Returning tips.")
        await lh.return_tips()


async def transfer_column(lh, source_wells, target_wells, vol, asp_height, asp_offsets, dsp_height, dsp_offsets, blowout, label):
    vols = [vol] * 8
    print(f"Aspirating {vol} uL from {label}...")
    await lh.aspirate(source_wells, vols=vols, liquid_height=asp_height, offsets=asp_offsets, blow_out_air_volume=[0.0] * 8)
    print(f"Dispensing {vol} uL to work plate...")
    await lh.dispense(target_wells, vols=vols, liquid_height=dsp_height, offsets=dsp_offsets, blow_out_air_volume=[blowout] * 8)


async def run_source_to_work(lh, r, dest_cols: List[int], discard_tips: bool, fresh_tips_per_reagent: bool):
    print("\n=== SOURCE-TO-WORK p10/p50 ===")

    if discard_tips and fresh_tips_per_reagent and len(dest_cols) * len(P10_STEPS) > 12:
        raise RuntimeError("fresh-tips-per-reagent needs more than one p10 rack for this many columns.")

    if discard_tips and fresh_tips_per_reagent:
        for dest_col in dest_cols:
            for src_col, vol, label in P10_STEPS:
                await lh.pick_up_tips(r["p10_cursor"].take())
                try:
                    await transfer_column(lh, r["source_96dw"][f"A{src_col}:H{src_col}"], wells_for_column(r["work_plate"], dest_col), vol, P10_SOURCE_96DW_ASP_HEIGHT, P10_SOURCE_96DW_ASP_OFFSETS, WORK_96WP_DSP_HEIGHT, WORK_96WP_DSP_OFFSETS, P10_BLOWOUT_AIR_VOLUME, f"{label} -> col {dest_col}")
                finally:
                    await finish_tips(lh, True)
        for dest_col in dest_cols:
            for src_col, vol, label in P50_STEPS:
                await lh.pick_up_tips(r["p50_cursor"].take())
                try:
                    await transfer_column(lh, r["source_96dw"][f"A{src_col}:H{src_col}"], wells_for_column(r["work_plate"], dest_col), vol, P50_SOURCE_96DW_ASP_HEIGHT, P50_SOURCE_96DW_ASP_OFFSETS, WORK_96WP_DSP_HEIGHT, WORK_96WP_DSP_OFFSETS, P50_BLOWOUT_AIR_VOLUME, f"{label} -> col {dest_col}")
                finally:
                    await finish_tips(lh, True)

    elif discard_tips:
        for dest_col in dest_cols:
            await lh.pick_up_tips(r["p10_cursor"].take())
            try:
                for src_col, vol, label in P10_STEPS:
                    await transfer_column(lh, r["source_96dw"][f"A{src_col}:H{src_col}"], wells_for_column(r["work_plate"], dest_col), vol, P10_SOURCE_96DW_ASP_HEIGHT, P10_SOURCE_96DW_ASP_OFFSETS, WORK_96WP_DSP_HEIGHT, WORK_96WP_DSP_OFFSETS, P10_BLOWOUT_AIR_VOLUME, f"{label} -> col {dest_col}")
            finally:
                await finish_tips(lh, True)
        for dest_col in dest_cols:
            await lh.pick_up_tips(r["p50_cursor"].take())
            try:
                for src_col, vol, label in P50_STEPS:
                    await transfer_column(lh, r["source_96dw"][f"A{src_col}:H{src_col}"], wells_for_column(r["work_plate"], dest_col), vol, P50_SOURCE_96DW_ASP_HEIGHT, P50_SOURCE_96DW_ASP_OFFSETS, WORK_96WP_DSP_HEIGHT, WORK_96WP_DSP_OFFSETS, P50_BLOWOUT_AIR_VOLUME, f"{label} -> col {dest_col}")
            finally:
                await finish_tips(lh, True)

    else:
        await lh.pick_up_tips(r["p10_tips"]["A1:H1"])
        try:
            for dest_col in dest_cols:
                for src_col, vol, label in P10_STEPS:
                    await transfer_column(lh, r["source_96dw"][f"A{src_col}:H{src_col}"], wells_for_column(r["work_plate"], dest_col), vol, P10_SOURCE_96DW_ASP_HEIGHT, P10_SOURCE_96DW_ASP_OFFSETS, WORK_96WP_DSP_HEIGHT, WORK_96WP_DSP_OFFSETS, P10_BLOWOUT_AIR_VOLUME, f"{label} -> col {dest_col}")
        finally:
            await finish_tips(lh, False)
        await lh.pick_up_tips(r["p50_tips"]["A1:H1"])
        try:
            for dest_col in dest_cols:
                for src_col, vol, label in P50_STEPS:
                    await transfer_column(lh, r["source_96dw"][f"A{src_col}:H{src_col}"], wells_for_column(r["work_plate"], dest_col), vol, P50_SOURCE_96DW_ASP_HEIGHT, P50_SOURCE_96DW_ASP_OFFSETS, WORK_96WP_DSP_HEIGHT, WORK_96WP_DSP_OFFSETS, P50_BLOWOUT_AIR_VOLUME, f"{label} -> col {dest_col}")
        finally:
            await finish_tips(lh, False)

    print("SUCCESS: source-to-work completed.")


async def move_plate_pos0_to_pos1(lh, r):
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]
    print("\n=== iSWAP rail35 pos0 -> pos1 ===")
    apply_iswap_pos0_pickup_offset(work_plate)
    mag_site = carrier[MAG_POS]
    original = Coordinate(mag_site.location.x, mag_site.location.y, mag_site.location.z)
    apply_iswap_pos1_dropoff_offset(mag_site)
    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, mag_site)
    mag_site.location = original
    print("SUCCESS: iSWAP rail35 pos0 -> pos1 completed.")


async def move_plate_pos1_to_pos0(lh, r):
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]
    print("\n=== iSWAP rail35 pos1 -> pos0 ===")
    apply_iswap_pos1_pickup_offset(work_plate)
    work_site = carrier[WORK_POS]
    original = Coordinate(work_site.location.x, work_site.location.y, work_site.location.z)
    apply_iswap_pos0_dropoff_offset(work_site)
    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, work_site)
    work_site.location = original
    print("SUCCESS: iSWAP rail35 pos1 -> pos0 completed.")


async def p300_add(lh, r, source_well_name: str, target_cols: List[int], discard_tips: bool):
    vols = [VOL_ETOH] * 8
    trough = r["trough"]
    plate = r["work_plate"]
    print(f"\n=== P300 ADD {source_well_name} -> mag cols {target_cols} ===")
    await lh.pick_up_tips(r["p300_cursor"].take() if discard_tips else r["p300_tips"]["A1:H1"])
    try:
        for col in target_cols:
            await lh.aspirate([trough[source_well_name][0]] * 8, vols=vols, liquid_height=P300_TROUGH_ASP_HEIGHT, offsets=P300_TROUGH_ASP_OFFSETS, blow_out_air_volume=[0.0] * 8)
            await lh.dispense(wells_for_column(plate, col), vols=vols, liquid_height=P300_MAG_DSP_HEIGHT, offsets=P300_MAG_DSP_OFFSETS, blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8)
    finally:
        await finish_tips(lh, discard_tips)


async def p300_remove(lh, r, source_cols: List[int], discard_tips: bool):
    vols = [VOL_ETOH_REMOVE] * 8
    trough = r["trough"]
    plate = r["work_plate"]
    print(f"\n=== P300 REMOVE mag cols {source_cols} -> waste {TROUGH_WASTE} ===")
    await lh.pick_up_tips(r["p300_cursor"].take() if discard_tips else r["p300_tips"]["A2:H2"])
    try:
        for col in source_cols:
            await lh.aspirate(wells_for_column(plate, col), vols=vols, liquid_height=P300_MAG_REMOVE_ASP_HEIGHT, offsets=P300_MAG_REMOVE_ASP_OFFSETS, blow_out_air_volume=[0.0] * 8)
            await lh.dispense([trough[TROUGH_WASTE][0]] * 8, vols=vols, liquid_height=P300_WASTE_DSP_HEIGHT, offsets=P300_WASTE_DSP_OFFSETS, blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8)
    finally:
        await finish_tips(lh, discard_tips)


async def run_ethanol_washes(lh, r, dest_cols: List[int], discard_tips: bool):
    print("\n=== TWO ETHANOL WASHES ===")
    await p300_add(lh, r, TROUGH_ETOH1, dest_cols, discard_tips)
    print(f"Incubating on magnet for {ETHANOL_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(ETHANOL_INCUBATION_SECONDS)
    await p300_remove(lh, r, dest_cols, discard_tips)
    await p300_add(lh, r, TROUGH_ETOH2, dest_cols, discard_tips)
    print(f"Incubating on magnet for {ETHANOL_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(ETHANOL_INCUBATION_SECONDS)
    await p300_remove(lh, r, dest_cols, discard_tips)
    print("SUCCESS: ethanol washes completed.")


async def main():
    parser = argparse.ArgumentParser(description="WGS preparation V2 production-style tip-advance scaffold.")
    parser.add_argument("--mode", choices=["deck", "rhodamine-4", "source-to-work", "full-v2"], default="full-v2")
    parser.add_argument("--dest-cols", default="1,2,3,4")
    parser.add_argument("--discard-tips", action="store_true", default=True)
    parser.add_argument("--fresh-tips-per-reagent", action="store_true")
    args = parser.parse_args()

    if args.dest_cols:
        dest_cols = parse_cols(args.dest_cols)
    elif args.mode == "rhodamine-4":
        dest_cols = [1, 2, 3, 4]
    else:
        dest_cols = [1]

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)
        if args.mode == "deck":
            print("Mode deck: assignment only.")
        elif args.mode in ("rhodamine-4", "source-to-work"):
            await run_source_to_work(lh, r, dest_cols, args.discard_tips, args.fresh_tips_per_reagent)
        elif args.mode == "full-v2":
            await run_source_to_work(lh, r, dest_cols, args.discard_tips, args.fresh_tips_per_reagent)
            await move_plate_pos0_to_pos1(lh, r)
            await run_ethanol_washes(lh, r, dest_cols, args.discard_tips)
            await move_plate_pos1_to_pos0(lh, r)
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
