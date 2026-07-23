import argparse
import asyncio
from typing import Dict, List

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
# WGS preparation (PTA) - p300 bead-clean add/remove + rail35 iSWAP focused test
#
# Active deck:
# - Rail 48 pos2 = p300 filter conductive tips.
# - Rail 35 pos0 = work 96WP, optional iSWAP source.
# - Rail 35 pos1 = bead-clean / magnetic-module 96WP position.
# - Rail 35 pos3 = 12-well reservoir.
#
# Notes:
# - Tips return by default; pass --discard-tips only for true wet/reagent runs.
# - p300 source aspirate height is set to 10.0 from the latest reservoir observation.
# - p300 tip rack prefers hamilton_96_tiprack_300uL_filter, which matched the NEST 345112 tips better
#   than the slim definition.
# - iSWAP pattern follows the old verified scaffold style: apply offset to pickup/dropoff target,
#   execute slow_iswap move_plate, then restore carrier site location for downstream LH.
# -----------------------------------------------------------------------------

TIP_RAIL = 48
P300_TIP_POS = 2

LABWARE_RAIL = 35
WORK_96WP_POS = 0
BEAD_CLEAN_POS = 1
TROUGH_POS = 3

ISWAP_OFFSET_X_MM = 0.0
ISWAP_OFFSET_Y_MM = 3.5
ISWAP_OFFSET_Z_MM = 40.0

TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"
TROUGH_WATER_TEST = "A5"
TROUGH_WASTE = "A12"

DEFAULT_ETOH_VOL = 200.0
DEFAULT_REMOVE_VOL = 180.0

P300_TROUGH_ASP_HEIGHT = [10.0] * 8
P300_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P300_BEAD_CLEAN_DSP_HEIGHT = [13.0] * 8
P300_BEAD_CLEAN_DSP_OFFSETS = [Coordinate(-0.60, 2.20, 21.0)] * 8

P300_BEAD_CLEAN_REMOVE_ASP_HEIGHT = [12.0] * 8
P300_BEAD_CLEAN_REMOVE_ASP_OFFSETS = [Coordinate(-0.15, 3.35, 0.0)] * 8

P300_WASTE_DSP_HEIGHT = [25.0] * 8
P300_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P300_ADD_BLOWOUT_AIR_VOLUME = 3.0
P300_REMOVE_BLOWOUT_AIR_VOLUME = 2.0

P300_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
    "hamilton_96_tiprack_300uL_filter_slim",
    "hamilton_96_tiprack_300ul_filter_slim",
]


def make_resource_from_candidates(label: str, name: str, candidates: List[str], nearby_terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)

    terms = [term.lower() for term in nearby_terms]
    available = sorted(n for n in dir(plr_resources) if any(term in n.lower() for term in terms))
    raise RuntimeError(
        f"Could not find a PyLabRobot resource factory for {label}. "
        f"Tried: {candidates}. Nearby installed names: {available[:160]}"
    )


def make_p300_tiprack(name: str):
    return make_resource_from_candidates(
        "p300 filter tips",
        name,
        P300_TIP_FACTORY_CANDIDATES,
        nearby_terms=["tip", "300", "htf"],
    )


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


def apply_verified_iswap_offset(resource):
    offset_location(resource, ISWAP_OFFSET_X_MM, ISWAP_OFFSET_Y_MM, ISWAP_OFFSET_Z_MM)


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning p300 bead-clean rail35 deck resources...")

    tip_carrier_48 = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier_48, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p300_tips = make_p300_tiprack(name="r48_p300_filter_tips")
    work_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_work_96wp")
    bead_clean_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_bead_clean_96wp")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_12w_reservoir")

    tip_carrier_48[P300_TIP_POS] = p300_tips
    labware_carrier[WORK_96WP_POS] = work_96wp
    labware_carrier[BEAD_CLEAN_POS] = bead_clean_96wp
    labware_carrier[TROUGH_POS] = trough

    print("\nAssigned resources:")
    print(f"tip_carrier_48: {tip_carrier_48.location}")
    print(f"labware_carrier: {labware_carrier.location}")
    print(f"p300_tips: {p300_tips.location}")
    print(f"work_96wp: {work_96wp.location}")
    print(f"bead_clean_96wp: {bead_clean_96wp.location}")
    print(f"trough: {trough.location}")

    print("\nP300 bead-clean geometry:")
    print(f"P300_TROUGH_ASP_HEIGHT = {P300_TROUGH_ASP_HEIGHT}")
    print(f"P300_TROUGH_ASP_OFFSETS = {P300_TROUGH_ASP_OFFSETS}")
    print(f"P300_BEAD_CLEAN_DSP_HEIGHT = {P300_BEAD_CLEAN_DSP_HEIGHT}")
    print(f"P300_BEAD_CLEAN_DSP_OFFSETS = {P300_BEAD_CLEAN_DSP_OFFSETS}")
    print(f"P300_BEAD_CLEAN_REMOVE_ASP_HEIGHT = {P300_BEAD_CLEAN_REMOVE_ASP_HEIGHT}")
    print(f"P300_BEAD_CLEAN_REMOVE_ASP_OFFSETS = {P300_BEAD_CLEAN_REMOVE_ASP_OFFSETS}")
    print(f"P300_WASTE_DSP_HEIGHT = {P300_WASTE_DSP_HEIGHT}")
    print(f"P300_WASTE_DSP_OFFSETS = {P300_WASTE_DSP_OFFSETS}")
    print(f"ISWAP_OFFSET_X/Y/Z = {ISWAP_OFFSET_X_MM}, {ISWAP_OFFSET_Y_MM}, {ISWAP_OFFSET_Z_MM}")

    return {
        "p300_tips": p300_tips,
        "work_96wp": work_96wp,
        "bead_clean_96wp": bead_clean_96wp,
        "trough": trough,
        "labware_carrier": labware_carrier,
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


async def run_tip_test(lh: LiquidHandler, r: Dict[str, object], tip_col: int):
    print(f"\n=== TIP TEST: p300 A{tip_col}:H{tip_col} pickup/return ===")
    await lh.pick_up_tips(tips_for_column(r["p300_tips"], tip_col))
    await lh.return_tips()
    print("SUCCESS: p300 pickup/return completed.")


async def move_work_plate_pos0_to_bead_clean_pos1(lh: LiquidHandler, r: Dict[str, object]):
    work_plate = r["work_96wp"]
    labware_carrier = r["labware_carrier"]

    print("\n=== iSWAP MOVE: rail35 pos0 work 96WP -> rail35 pos1 bead-clean 96WP site ===")
    print(f"Using iSWAP offset X={ISWAP_OFFSET_X_MM}, Y={ISWAP_OFFSET_Y_MM}, Z={ISWAP_OFFSET_Z_MM} mm")

    print(f"Original work plate location: {work_plate.location}")
    apply_verified_iswap_offset(work_plate)
    print(f"Offset work plate pickup location: {work_plate.location}")

    bead_clean_site = labware_carrier[BEAD_CLEAN_POS]
    original_site_location = Coordinate(bead_clean_site.location.x, bead_clean_site.location.y, bead_clean_site.location.z)

    print(f"Original bead-clean site location: {bead_clean_site.location}")
    apply_verified_iswap_offset(bead_clean_site)
    print(f"Offset bead-clean dropoff location: {bead_clean_site.location}")

    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, bead_clean_site)

    bead_clean_site.location = original_site_location
    print(f"Restored rail35 pos1 bead-clean site location for LH: {bead_clean_site.location}")
    print("iSWAP move to rail35 pos1 complete.")


async def add_from_reservoir_to_bead_clean(lh, r, source_well_name: str, dest_cols: List[int], vol: float, tip_col: int, discard_tips: bool):
    trough = r["trough"]
    bead_clean_96wp = r["bead_clean_96wp"]
    vols = [vol] * 8

    print("\n=== P300 ADD: rail35 pos3 reservoir -> rail35 pos1 bead-clean plate ===")
    print(f"Source reservoir well: {source_well_name}; destination columns: {dest_cols}; volume: {vol} uL")
    await lh.pick_up_tips(tips_for_column(r["p300_tips"], tip_col))

    try:
        for dest_col in dest_cols:
            print(f"Aspirating {vol} uL x8 from reservoir {source_well_name}...")
            await lh.aspirate(
                [trough[source_well_name][0]] * 8,
                vols=vols,
                liquid_height=P300_TROUGH_ASP_HEIGHT,
                offsets=P300_TROUGH_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )

            print(f"Dispensing {vol} uL x8 to bead-clean plate column {dest_col}...")
            await lh.dispense(
                wells_for_column(bead_clean_96wp, dest_col),
                vols=vols,
                liquid_height=P300_BEAD_CLEAN_DSP_HEIGHT,
                offsets=P300_BEAD_CLEAN_DSP_OFFSETS,
                blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8,
            )
    finally:
        await finish_tips(lh, discard_tips=discard_tips)

    print("SUCCESS: p300 reservoir add completed.")


async def remove_from_bead_clean_to_waste(lh, r, source_cols: List[int], waste_well_name: str, vol: float, tip_col: int, discard_tips: bool):
    trough = r["trough"]
    bead_clean_96wp = r["bead_clean_96wp"]
    vols = [vol] * 8

    print("\n=== P300 REMOVE: rail35 pos1 bead-clean plate -> rail35 pos3 reservoir waste ===")
    print(f"Source columns: {source_cols}; waste reservoir well: {waste_well_name}; volume: {vol} uL")
    await lh.pick_up_tips(tips_for_column(r["p300_tips"], tip_col))

    try:
        for source_col in source_cols:
            print(f"Aspirating {vol} uL x8 from bead-clean plate column {source_col}...")
            await lh.aspirate(
                wells_for_column(bead_clean_96wp, source_col),
                vols=vols,
                liquid_height=P300_BEAD_CLEAN_REMOVE_ASP_HEIGHT,
                offsets=P300_BEAD_CLEAN_REMOVE_ASP_OFFSETS,
                blow_out_air_volume=[0.0] * 8,
            )

            print(f"Dispensing {vol} uL x8 to waste reservoir {waste_well_name}...")
            await lh.dispense(
                [trough[waste_well_name][0]] * 8,
                vols=vols,
                liquid_height=P300_WASTE_DSP_HEIGHT,
                offsets=P300_WASTE_DSP_OFFSETS,
                blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8,
            )
    finally:
        await finish_tips(lh, discard_tips=discard_tips)

    print("SUCCESS: p300 removal-to-waste completed.")


async def main():
    parser = argparse.ArgumentParser(description="p300 bead-clean add/remove and rail35 pos0->pos1 iSWAP test.")
    parser.add_argument(
        "--mode",
        choices=["deck", "tips", "iswap", "add", "remove", "add-remove", "iswap-add"],
        default="deck",
    )
    parser.add_argument("--dest-cols", default="1")
    parser.add_argument("--source-well", default=TROUGH_WATER_TEST)
    parser.add_argument("--waste-well", default=TROUGH_WASTE)
    parser.add_argument("--add-vol", type=float, default=DEFAULT_ETOH_VOL)
    parser.add_argument("--remove-vol", type=float, default=DEFAULT_REMOVE_VOL)
    parser.add_argument("--add-tip-col", type=int, default=1)
    parser.add_argument("--remove-tip-col", type=int, default=2)
    parser.add_argument("--discard-tips", action="store_true")
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        resources = await assign_deck(lh)
        dest_cols = parse_cols(args.dest_cols)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No tip pickup or liquid handling executed.")
        elif args.mode == "tips":
            await run_tip_test(lh, resources, tip_col=args.add_tip_col)
        elif args.mode == "iswap":
            await move_work_plate_pos0_to_bead_clean_pos1(lh, resources)
        elif args.mode == "add":
            await add_from_reservoir_to_bead_clean(lh, resources, args.source_well, dest_cols, args.add_vol, args.add_tip_col, args.discard_tips)
        elif args.mode == "remove":
            await remove_from_bead_clean_to_waste(lh, resources, dest_cols, args.waste_well, args.remove_vol, args.remove_tip_col, args.discard_tips)
        elif args.mode == "add-remove":
            await add_from_reservoir_to_bead_clean(lh, resources, args.source_well, dest_cols, args.add_vol, args.add_tip_col, args.discard_tips)
            print("NOTE: Protocol incubation after ethanol add is 30 seconds on magnet before removal.")
            await remove_from_bead_clean_to_waste(lh, resources, dest_cols, args.waste_well, args.remove_vol, args.remove_tip_col, args.discard_tips)
        elif args.mode == "iswap-add":
            await move_work_plate_pos0_to_bead_clean_pos1(lh, resources)
            await add_from_reservoir_to_bead_clean(lh, resources, args.source_well, dest_cols, args.add_vol, args.add_tip_col, args.discard_tips)
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
