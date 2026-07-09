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
# whole-genome sequencing V2 truth-set / biovalidation scaffold: rail35 pos1 source, pos2 mag
#
# KEY PORT FROM CAMERA/RAIL35 WORK:
# - rail35 pos0 = destination/work 96WP, unchanged
# - rail35 pos1 = CHILLED SOURCE 96WP, not 96DW
# - rail35 pos2 = magnetic rack / cleanup site
# - rail35 pos3 = 12-well reservoir/trough
#
# CRITICAL GEOMETRY CHANGE:
# - Source plate at pos1 uses the SAME 96WP plate definition as destination pos0.
# - Source plate at pos1 uses the SAME XY offsets as destination pos0.
# - Do NOT use the old 96DW source offsets for this script.
#
# This file is a clean handoff scaffold for a first truth-set pilot. It should be
# reviewed and adjusted in the next development chat before running live samples.
# -----------------------------------------------------------------------------

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1
P300_TIP_POS = 2
P1000_TIP_POS = 3  # reserved

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1
MAG_POS = 2
TROUGH_POS = 3

DEFAULT_DEST_COLS = [1]

# iSWAP offsets: previously validated on rail35 with pos0 work plate.
# This scaffold ports the magnetic site from pos1 to pos2. Validate with --mode deck
# and a dry iSWAP-only run before live samples.
ISWAP_OFFSET_X_MM = 0.0
ISWAP_OFFSET_Y_MM = 3.5
ISWAP_POS0_PICKUP_Z_MM = 19.0
ISWAP_MAG_DROPOFF_Z_MM = 40.0
ISWAP_MAG_PICKUP_Z_MM = 42.0
ISWAP_POS0_DROPOFF_Z_MM = 20.0

# Source reagent/source-column pattern. Update labels/volumes for actual truth-set run.
P10_STEPS: List[Tuple[int, float, str]] = [
    (1, 3.0, "Lysis Mix / small reagent 1"),
    (2, 6.0, "Reaction Mix / small reagent 2"),
    (3, 3.0, "DNA Prep Master Mix / small reagent 3"),
    (4, 4.0, "FERAT Master Mix / small reagent 4"),
    (5, 5.0, "UDI Adapter / small reagent 5"),
    (6, 5.0, "LP2L / small reagent 6"),
]
P50_STEPS: List[Tuple[int, float, str]] = [
    (7, 20.0, "Amplification Master Mix / p50 reagent"),
]

# Reservoir layout for ethanol/wash camera/cleanup module.
TROUGH_WASH1 = "A2"
TROUGH_WASH2 = "A3"
TROUGH_WASTE = "A12"

VOL_WASH = 200.0
VOL_REMOVE = 180.0
WASH_INCUBATION_SECONDS = 30

# -----------------------------------------------------------------------------
# 96WP geometry shared by destination pos0 and source pos1.
# -----------------------------------------------------------------------------

# Latest droplet-friendly destination dispense height from camera/debug work.
# Smoke-test spine update: work/source 96WP XY offset moved slightly left in X
# for THIS pos1-source/pos2-mag scaffold only (-0.15 -> -0.30).
# Review before live chemistry if exact immersion/contact height matters.
WORK_96WP_DSP_HEIGHT = [7.0] * 8
WORK_96WP_DSP_OFFSETS = [Coordinate(-0.30, 3.35, 0.0)] * 8

# KEY: source at rail35 pos1 is a 96WP and deliberately uses the SAME offsets
# as the destination/work 96WP. This replaces the old 96DW source geometry.
SOURCE_96WP_ASP_HEIGHT = [7.0] * 8
SOURCE_96WP_ASP_OFFSETS = WORK_96WP_DSP_OFFSETS

P10_BLOWOUT_AIR_VOLUME = 2.0
P50_BLOWOUT_AIR_VOLUME = 6.0

# P300 wash geometry ported to MAG_POS = 2.
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


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


def parse_dest_cols(dest_cols: str) -> List[int]:
    if not dest_cols:
        return DEFAULT_DEST_COLS
    cols = [int(x.strip()) for x in dest_cols.split(",") if x.strip()]
    for col in cols:
        if col < 1 or col > 12:
            raise ValueError(f"Destination column out of range: {col}")
    return cols


def offset_location(resource, dx=0.0, dy=0.0, dz=0.0):
    loc = resource.location
    if loc is None:
        raise RuntimeError(f"{resource.name} has no location.")
    resource.location = Coordinate(loc.x + dx, loc.y + dy, loc.z + dz)


def apply_iswap_pos0_pickup_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS0_PICKUP_Z_MM)


def apply_iswap_mag_dropoff_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_MAG_DROPOFF_Z_MM)


def apply_iswap_mag_pickup_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_MAG_PICKUP_Z_MM)


def apply_iswap_pos0_dropoff_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_POS0_DROPOFF_Z_MM)


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning whole-genome sequencing V2 truth-set scaffold deck...")
    print("KEY LAYOUT: rail35 pos1 = 96WP source, rail35 pos2 = magnetic rack site.")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")

    # KEY: source and destination are the same 96WP definition.
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_work_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_chilled_source_96wp")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_12w_reservoir")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips

    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96WP_POS] = source_96wp
    # Do not assign a plate to MAG_POS; carrier[MAG_POS] is the dropoff site.
    labware_carrier[TROUGH_POS] = trough

    print("\nDeck resources:")
    print("  rail48 pos0 = p10 tips")
    print("  rail48 pos1 = p50 tips")
    print("  rail48 pos2 = p300 tips")
    print("  rail35 pos0 = destination/work 96WP")
    print("  rail35 pos1 = CHILLED SOURCE 96WP")
    print("  rail35 pos2 = magnetic rack / cleanup site")
    print("  rail35 pos3 = reservoir/trough")

    print("\nShared 96WP geometry:")
    print(f"  WORK_96WP_DSP_HEIGHT = {WORK_96WP_DSP_HEIGHT}")
    print(f"  WORK_96WP_DSP_OFFSETS = {WORK_96WP_DSP_OFFSETS}")
    print(f"  SOURCE_96WP_ASP_HEIGHT = {SOURCE_96WP_ASP_HEIGHT}")
    print(f"  SOURCE_96WP_ASP_OFFSETS = {SOURCE_96WP_ASP_OFFSETS}")
    print("  Source pos1 intentionally uses same plate definition and XY offsets as work pos0.")

    print("\nMagnetic rack/wash geometry:")
    print(f"  MAG_POS = {MAG_POS}")
    print(f"  P300_MAG_DSP_OFFSETS = {P300_MAG_DSP_OFFSETS}")
    print(f"  P300_MAG_REMOVE_ASP_HEIGHT = {P300_MAG_REMOVE_ASP_HEIGHT}")
    print(f"  P300_MAG_REMOVE_ASP_OFFSETS = {P300_MAG_REMOVE_ASP_OFFSETS}")

    print("\niSWAP geometry:")
    print(f"  pos0 pickup Z = {ISWAP_POS0_PICKUP_Z_MM}")
    print(f"  mag pos2 dropoff Z = {ISWAP_MAG_DROPOFF_Z_MM}")
    print(f"  mag pos2 pickup Z = {ISWAP_MAG_PICKUP_Z_MM}")
    print(f"  pos0 dropoff Z = {ISWAP_POS0_DROPOFF_Z_MM}")

    return {
        "labware_carrier": labware_carrier,
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "p300_tips": p300_tips,
        "work_plate": work_plate,
        "source_96wp": source_96wp,
        "trough": trough,
        "p10_cursor": TipCursor(p10_tips, "p10"),
        "p50_cursor": TipCursor(p50_tips, "p50"),
        "p300_cursor": TipCursor(p300_tips, "p300"),
    }


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips...")
        await lh.discard_tips()
    else:
        print("Returning tips...")
        await lh.return_tips()


async def transfer_column(
    lh: LiquidHandler,
    r: Dict[str, object],
    src_col: int,
    dest_col: int,
    vol: float,
    blowout: float,
    label: str,
):
    vols = [vol] * 8

    print(f"Aspirating {vol} uL from source 96WP pos1 col {src_col} ({label}) -> work col {dest_col}...")
    await lh.aspirate(
        r["source_96wp"][f"A{src_col}:H{src_col}"],
        vols=vols,
        liquid_height=SOURCE_96WP_ASP_HEIGHT,
        offsets=SOURCE_96WP_ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL to work 96WP pos0 col {dest_col} with blowout {blowout} uL...")
    await lh.dispense(
        wells_for_column(r["work_plate"], dest_col),
        vols=vols,
        liquid_height=WORK_96WP_DSP_HEIGHT,
        offsets=WORK_96WP_DSP_OFFSETS,
        blow_out_air_volume=[blowout] * 8,
    )


async def run_source_to_work(lh: LiquidHandler, r: Dict[str, object], dest_cols: List[int], discard_tips: bool):
    print("\n=== SOURCE-TO-WORK: source 96WP rail35 pos1 -> work 96WP rail35 pos0 ===")
    print(f"Destination columns: {dest_cols}")
    print("Source pos1 is a 96WP and uses same offsets as work pos0.")

    for dest_col in dest_cols:
        print(f"\n--- p10 source-to-work into destination column {dest_col} ---")
        await lh.pick_up_tips(r["p10_cursor"].take() if discard_tips else r["p10_tips"]["A1:H1"])
        try:
            for src_col, vol, label in P10_STEPS:
                await transfer_column(lh, r, src_col, dest_col, vol, P10_BLOWOUT_AIR_VOLUME, label)
        finally:
            await finish_tips(lh, discard_tips)

    for dest_col in dest_cols:
        print(f"\n--- p50 source-to-work into destination column {dest_col} ---")
        await lh.pick_up_tips(r["p50_cursor"].take() if discard_tips else r["p50_tips"]["A1:H1"])
        try:
            for src_col, vol, label in P50_STEPS:
                await transfer_column(lh, r, src_col, dest_col, vol, P50_BLOWOUT_AIR_VOLUME, label)
        finally:
            await finish_tips(lh, discard_tips)

    print("SUCCESS: source-to-work completed.")


async def move_plate_pos0_to_mag_pos2(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== iSWAP MOVE: rail35 pos0 work plate -> rail35 pos2 magnetic rack ===")
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]

    print(f"Original plate pickup location: {work_plate.location}")
    apply_iswap_pos0_pickup_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")

    mag_site = carrier[MAG_POS]
    original_mag_location = Coordinate(mag_site.location.x, mag_site.location.y, mag_site.location.z)

    print(f"Original mag pos2 site location: {mag_site.location}")
    apply_iswap_mag_dropoff_offset(mag_site)
    print(f"Offset mag pos2 dropoff location: {mag_site.location}")

    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, mag_site)

    mag_site.location = original_mag_location
    print(f"Restored mag pos2 site location: {mag_site.location}")
    print("SUCCESS: iSWAP rail35 pos0 -> pos2 completed.")


async def move_plate_mag_pos2_to_pos0(lh: LiquidHandler, r: Dict[str, object]):
    print("\n=== iSWAP MOVE: rail35 pos2 magnetic rack -> rail35 pos0 work site ===")
    work_plate = r["work_plate"]
    carrier = r["labware_carrier"]

    print(f"Current plate pickup location before offset: {work_plate.location}")
    apply_iswap_mag_pickup_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")

    work_site = carrier[WORK_POS]
    original_work_location = Coordinate(work_site.location.x, work_site.location.y, work_site.location.z)

    print(f"Original pos0 work site location: {work_site.location}")
    apply_iswap_pos0_dropoff_offset(work_site)
    print(f"Offset pos0 dropoff location: {work_site.location}")

    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, work_site)

    work_site.location = original_work_location
    print(f"Restored pos0 work site location: {work_site.location}")
    print("SUCCESS: iSWAP rail35 pos2 -> pos0 completed.")


async def p300_add(lh: LiquidHandler, r: Dict[str, object], source_well_name: str, dest_cols: List[int], discard_tips: bool):
    vols = [VOL_WASH] * 8
    trough = r["trough"]
    plate = r["work_plate"]

    print(f"\n=== P300 ADD: reservoir {source_well_name} -> mag pos2 plate columns {dest_cols}, {VOL_WASH} uL ===")
    await lh.pick_up_tips(r["p300_cursor"].take() if discard_tips else r["p300_tips"]["A1:H1"])
    try:
        for col in dest_cols:
            print(f"Aspirating {VOL_WASH} uL x8 from reservoir {source_well_name}...")
            await lh.aspirate(
                [trough[source_well_name][0]] * 8,
                vols=vols,
                liquid_height=P300_TROUGH_ASP_HEIGHT,
                offsets=P300_TROUGH_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )

            print(f"Dispensing {VOL_WASH} uL x8 to mag plate column {col}...")
            await lh.dispense(
                wells_for_column(plate, col),
                vols=vols,
                liquid_height=P300_MAG_DSP_HEIGHT,
                offsets=P300_MAG_DSP_OFFSETS,
                blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8,
            )
    finally:
        await finish_tips(lh, discard_tips)


async def p300_remove(lh: LiquidHandler, r: Dict[str, object], dest_cols: List[int], discard_tips: bool):
    vols = [VOL_REMOVE] * 8
    trough = r["trough"]
    plate = r["work_plate"]

    print(f"\n=== P300 REMOVE: mag pos2 plate columns {dest_cols} -> waste {TROUGH_WASTE}, {VOL_REMOVE} uL ===")
    await lh.pick_up_tips(r["p300_cursor"].take() if discard_tips else r["p300_tips"]["A2:H2"])
    try:
        for col in dest_cols:
            print(f"Aspirating {VOL_REMOVE} uL x8 from mag plate column {col}...")
            await lh.aspirate(
                wells_for_column(plate, col),
                vols=vols,
                liquid_height=P300_MAG_REMOVE_ASP_HEIGHT,
                offsets=P300_MAG_REMOVE_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )

            print(f"Dispensing {VOL_REMOVE} uL x8 to reservoir waste {TROUGH_WASTE}...")
            await lh.dispense(
                [trough[TROUGH_WASTE][0]] * 8,
                vols=vols,
                liquid_height=P300_WASTE_DSP_HEIGHT,
                offsets=P300_WASTE_DSP_OFFSETS,
                blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8,
            )
    finally:
        await finish_tips(lh, discard_tips)


async def run_two_washes(lh: LiquidHandler, r: Dict[str, object], dest_cols: List[int], discard_tips: bool):
    print("\n=== TWO WASH CYCLES ON MAGNETIC RACK AT rail35 pos2 ===")
    await p300_add(lh, r, TROUGH_WASH1, dest_cols, discard_tips)
    print(f"Incubating on magnet for {WASH_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(WASH_INCUBATION_SECONDS)
    await p300_remove(lh, r, dest_cols, discard_tips)

    await p300_add(lh, r, TROUGH_WASH2, dest_cols, discard_tips)
    print(f"Incubating on magnet for {WASH_INCUBATION_SECONDS} seconds...")
    await asyncio.sleep(WASH_INCUBATION_SECONDS)
    await p300_remove(lh, r, dest_cols, discard_tips)

    print("SUCCESS: two wash cycles completed.")


async def main():
    parser = argparse.ArgumentParser(description="whole-genome sequencing V2 truth-set scaffold: source pos1 96WP, mag pos2.")
    parser.add_argument("--mode", choices=["deck", "source-to-work", "iswap-only", "full-v2"], default="deck")
    parser.add_argument("--dest-cols", default="1")
    parser.add_argument("--discard-tips", action="store_true")
    args = parser.parse_args()

    dest_cols = parse_dest_cols(args.dest_cols)

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No movement or liquid handling executed.")
            return

        if args.mode == "source-to-work":
            await run_source_to_work(lh, r, dest_cols, args.discard_tips)
            return

        if args.mode == "iswap-only":
            await move_plate_pos0_to_mag_pos2(lh, r)
            await asyncio.sleep(2)
            await move_plate_mag_pos2_to_pos0(lh, r)
            return

        if args.mode == "full-v2":
            await run_source_to_work(lh, r, dest_cols, args.discard_tips)
            await move_plate_pos0_to_mag_pos2(lh, r)
            await run_two_washes(lh, r, dest_cols, args.discard_tips)
            await move_plate_mag_pos2_to_pos0(lh, r)
            print("\nSUCCESS: full V2 truth-set scaffold completed.")
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
