import argparse
import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional

from pathlib import Path as _MethodPath
import sys as _method_sys

_method_root = next(parent for parent in _MethodPath(__file__).resolve().parents if parent.name == "hamilton-star")
if str(_method_root) not in _method_sys.path:
    _method_sys.path.insert(0, str(_method_root))
from operator_parameters import required_positive, required_nonnegative, required_text

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

# PCR enrichment library preparation - round 1 cleanup dry motion scaffold, column 1 only
#
# Purpose:
# - Keep the existing WGS/validation rail35/rail48 carrier approach.
# - Dry/air-move test the round 1 cleanup motions before any real cleanup-reagent use.
# - Cleanup values come from the operator-approved local method profile.
# - This script does not mix; wet-method handoffs remain in the approved local SOP.
# - Default behavior returns tips because this is a dry offset/motion script.
# - Add --discard-tips only when deliberately testing production-style tip discard.
#
# Physical deck:
#   rail48 pos1 = p50 tips for residual ethanol removal
#   rail48 pos2 = p300 tips for beads/ethanol/elution/supernatant removal
#   rail35 pos2 = magnetic rack with cleanup plate/strip, column 1 only
#   rail35 pos3 = 12-well reservoir/trough
#
# Reservoir map:
#   A1  = cleanup beads / bead mimic
#   A2  = ethanol wash 1 / ethanol mimic
#   A3  = ethanol wash 2 / ethanol mimic
#   A4  = H2O elution / elution mimic
#   A12 = waste
#
# Modes:
#   deck
#   beads-add-dry
#   supernatant-remove-dry
#   ethanol-add1-dry
#   ethanol-remove1-dry
#   ethanol-add2-dry
#   ethanol-remove2-dry
#   residual-ethanol-remove-dry
#   elution-add-dry
#   ethanol-cycle-dry
#   ethanol-cycle-residual-dry
#   all-dry

TIP_RAIL = 48
P50_TIP_POS = 1
P300_TIP_POS = 2

LABWARE_RAIL = 35
MAG_POS = 2
TROUGH_POS = 3

DEST_COL = 1

TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"
TROUGH_WASTE = "A12"

# Runtime PCR enrichment values come from the operator-approved local profile.
VOL_BEADS = required_positive("pcr_enrichment.cleanup.bead_volume_ul")
VOL_SUPERNATANT_REMOVE = required_positive("pcr_enrichment.cleanup.supernatant_remove_ul")
VOL_ETHANOL_ADD = required_positive("pcr_enrichment.cleanup.wash_add_ul")
VOL_ETHANOL_REMOVE = required_positive("pcr_enrichment.cleanup.wash_remove_ul")
VOL_RESIDUAL_ETHANOL_REMOVE = required_positive("pcr_enrichment.cleanup.residual_remove_ul")
VOL_ELUTION = required_positive("pcr_enrichment.cleanup.elution_ul")
WASH_INCUBATION_SECONDS = required_nonnegative("pcr_enrichment.cleanup.wash_incubation_seconds")

# Reuse the existing tuned validation cleanup geometry for rail35 pos2 mag + rail35 pos3 trough.
P300_TROUGH_ASP_HEIGHT = [10.0] * 8
P300_TROUGH_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P300_MAG_DSP_HEIGHT = [10.5] * 8
P300_MAG_DSP_OFFSETS = [Coordinate(-0.72, 2.20, 21.0)] * 8

P300_MAG_REMOVE_ASP_HEIGHT = [29.0] * 8
P300_MAG_REMOVE_ASP_OFFSETS = [Coordinate(-0.72, 3.35, 0.0)] * 8

P300_WASTE_DSP_HEIGHT = [12.0] * 8
P300_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P300_ADD_BLOWOUT_AIR_VOLUME = 3.0
P300_REMOVE_BLOWOUT_AIR_VOLUME = 2.0

# Finer p50 residual ethanol removal after p300 ethanol removal.
P50_MAG_RESIDUAL_ASP_HEIGHT = [26.0] * 8
P50_MAG_RESIDUAL_ASP_OFFSETS = [Coordinate(-0.72, 3.35, 0.0)] * 8
P50_WASTE_DSP_HEIGHT = [8.0] * 8
P50_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P50_RESIDUAL_BLOWOUT_AIR_VOLUME = 2.0

P50_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_50uL_filter", "hamilton_96_tiprack_50ul_filter"]
P300_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_300uL_filter",
    "hamilton_96_tiprack_300ul_filter",
    "hamilton_96_tiprack_300uL_filter_slim",
    "hamilton_96_tiprack_300ul_filter_slim",
]


@dataclass
class CleanupAction:
    mode: str
    label: str
    kind: str
    source_well: Optional[str]
    volume_ul: float


ACTIONS = {
    "beads-add-dry": CleanupAction("beads-add-dry", "Add cleanup beads / bead mimic", "add", TROUGH_BEADS, VOL_BEADS),
    "supernatant-remove-dry": CleanupAction("supernatant-remove-dry", "Remove post-bead supernatant to waste", "remove", None, VOL_SUPERNATANT_REMOVE),
    "ethanol-add1-dry": CleanupAction("ethanol-add1-dry", "Add ethanol wash 1", "add", TROUGH_ETOH1, VOL_ETHANOL_ADD),
    "ethanol-remove1-dry": CleanupAction("ethanol-remove1-dry", "Remove ethanol wash 1 to waste", "remove", None, VOL_ETHANOL_REMOVE),
    "ethanol-add2-dry": CleanupAction("ethanol-add2-dry", "Add ethanol wash 2", "add", TROUGH_ETOH2, VOL_ETHANOL_ADD),
    "ethanol-remove2-dry": CleanupAction("ethanol-remove2-dry", "Remove ethanol wash 2 to waste", "remove", None, VOL_ETHANOL_REMOVE),
    "residual-ethanol-remove-dry": CleanupAction("residual-ethanol-remove-dry", "Remove residual/dead ethanol with p50 to waste", "residual_remove_p50", None, VOL_RESIDUAL_ETHANOL_REMOVE),
    "elution-add-dry": CleanupAction("elution-add-dry", "Add H2O elution buffer", "add", TROUGH_ELUTION, VOL_ELUTION),
}


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


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning PCR enrichment round 1 cleanup dry deck: mag pos2 + trough pos3...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    mag_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos2_pcr_enrichment_round1_cleanup_mag_96wp")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_pcr_enrichment_cleanup_12w_reservoir")

    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips
    labware_carrier[MAG_POS] = mag_plate
    labware_carrier[TROUGH_POS] = trough

    print("\nDeck:")
    print("  rail48 pos1 = p50 tips for residual ethanol removal")
    print("  rail48 pos2 = p300 tips")
    print("  rail35 pos2 = magnetic rack / PCR1 cleanup plate")
    print("  rail35 pos3 = 12-well reservoir/trough")
    print("  cleanup column = 1 only")

    print("\nReservoir map:")
    print(f"  {TROUGH_BEADS} = cleanup beads / bead mimic")
    print(f"  {TROUGH_ETOH1} = ethanol wash 1 / ethanol mimic")
    print(f"  {TROUGH_ETOH2} = ethanol wash 2 / ethanol mimic")
    print(f"  {TROUGH_ELUTION} = H2O elution / mimic")
    print(f"  {TROUGH_WASTE} = waste")

    print("\nPCR enrichment round 1 cleanup values from the operator profile:")
    print(f"  beads add = {VOL_BEADS} uL x8")
    print(f"  supernatant remove = {VOL_SUPERNATANT_REMOVE} uL x8")
    print(f"  ethanol add/remove = {VOL_ETHANOL_ADD}/{VOL_ETHANOL_REMOVE} uL x8")
    print(f"  residual ethanol remove = {VOL_RESIDUAL_ETHANOL_REMOVE} uL x8 with p50")
    print(f"  elution add = {VOL_ELUTION} uL x8")
    print(f"  wash incubation handoff = {WASH_INCUBATION_SECONDS} sec per approved local SOP")

    print("\nCurrent p300 geometry:")
    print(f"  P300_TROUGH_ASP_HEIGHT = {P300_TROUGH_ASP_HEIGHT}")
    print(f"  P300_TROUGH_ASP_OFFSETS = {P300_TROUGH_ASP_OFFSETS}")
    print(f"  P300_MAG_DSP_HEIGHT = {P300_MAG_DSP_HEIGHT}")
    print(f"  P300_MAG_DSP_OFFSETS = {P300_MAG_DSP_OFFSETS}")
    print(f"  P300_MAG_REMOVE_ASP_HEIGHT = {P300_MAG_REMOVE_ASP_HEIGHT}")
    print(f"  P300_MAG_REMOVE_ASP_OFFSETS = {P300_MAG_REMOVE_ASP_OFFSETS}")
    print(f"  P300_WASTE_DSP_HEIGHT = {P300_WASTE_DSP_HEIGHT}")
    print(f"  P300_WASTE_DSP_OFFSETS = {P300_WASTE_DSP_OFFSETS}")

    print("\np50 residual ethanol geometry:")
    print(f"  P50_MAG_RESIDUAL_ASP_HEIGHT = {P50_MAG_RESIDUAL_ASP_HEIGHT}")
    print(f"  P50_MAG_RESIDUAL_ASP_OFFSETS = {P50_MAG_RESIDUAL_ASP_OFFSETS}")
    print(f"  P50_WASTE_DSP_HEIGHT = {P50_WASTE_DSP_HEIGHT}")
    print(f"  P50_WASTE_DSP_OFFSETS = {P50_WASTE_DSP_OFFSETS}")

    return {"p50_tips": p50_tips, "p300_tips": p300_tips, "mag_plate": mag_plate, "trough": trough}


async def finish_tips(lh: LiquidHandler, discard_tips: bool, tip_kind: str):
    if discard_tips:
        print(f"Discarding {tip_kind} tips...")
        await lh.discard_tips()
    else:
        print(f"Returning {tip_kind} tips...")
        await lh.return_tips()


async def p300_add_from_trough(lh: LiquidHandler, r: Dict[str, object], source_well_name: str, volume_ul: float, discard_tips: bool, tip_col: int):
    vols = [volume_ul] * 8
    trough = r["trough"]
    plate = r["mag_plate"]

    print(f"\nP300 ADD DRY: reservoir {source_well_name} -> mag pos2 plate col {DEST_COL}; {volume_ul} uL x8")
    print(f"Using p300 tip column {tip_col}; discard_tips={discard_tips}")
    await lh.pick_up_tips(r["p300_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        print(f"Aspirating from reservoir {source_well_name}...")
        await lh.aspirate(
            [trough[source_well_name][0]] * 8,
            vols=vols,
            liquid_height=P300_TROUGH_ASP_HEIGHT,
            offsets=P300_TROUGH_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        print(f"Dispensing to mag plate column {DEST_COL}...")
        await lh.dispense(
            wells_for_column(plate, DEST_COL),
            vols=vols,
            liquid_height=P300_MAG_DSP_HEIGHT,
            offsets=P300_MAG_DSP_OFFSETS,
            blow_out_air_volume=[P300_ADD_BLOWOUT_AIR_VOLUME] * 8,
        )
    finally:
        await finish_tips(lh, discard_tips, "p300")


async def p300_remove_to_waste(lh: LiquidHandler, r: Dict[str, object], volume_ul: float, discard_tips: bool, tip_col: int):
    vols = [volume_ul] * 8
    trough = r["trough"]
    plate = r["mag_plate"]

    print(f"\nP300 REMOVE DRY: mag pos2 plate col {DEST_COL} -> waste {TROUGH_WASTE}; {volume_ul} uL x8")
    print(f"Using p300 tip column {tip_col}; discard_tips={discard_tips}")
    await lh.pick_up_tips(r["p300_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        print(f"Aspirating from mag plate column {DEST_COL}...")
        await lh.aspirate(
            wells_for_column(plate, DEST_COL),
            vols=vols,
            liquid_height=P300_MAG_REMOVE_ASP_HEIGHT,
            offsets=P300_MAG_REMOVE_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        print(f"Dispensing to waste {TROUGH_WASTE}...")
        await lh.dispense(
            [trough[TROUGH_WASTE][0]] * 8,
            vols=vols,
            liquid_height=P300_WASTE_DSP_HEIGHT,
            offsets=P300_WASTE_DSP_OFFSETS,
            blow_out_air_volume=[P300_REMOVE_BLOWOUT_AIR_VOLUME] * 8,
        )
    finally:
        await finish_tips(lh, discard_tips, "p300")


async def p50_remove_residual_ethanol_to_waste(lh: LiquidHandler, r: Dict[str, object], volume_ul: float, discard_tips: bool, tip_col: int):
    vols = [volume_ul] * 8
    trough = r["trough"]
    plate = r["mag_plate"]

    print(f"\nP50 RESIDUAL ETHANOL REMOVE DRY: mag pos2 plate col {DEST_COL} -> waste {TROUGH_WASTE}; {volume_ul} uL x8")
    print(f"Using p50 tip column {tip_col}; discard_tips={discard_tips}")
    await lh.pick_up_tips(r["p50_tips"][f"A{tip_col}:H{tip_col}"])
    try:
        print(f"Aspirating residual ethanol from mag plate column {DEST_COL} with p50...")
        await lh.aspirate(
            wells_for_column(plate, DEST_COL),
            vols=vols,
            liquid_height=P50_MAG_RESIDUAL_ASP_HEIGHT,
            offsets=P50_MAG_RESIDUAL_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )
        print(f"Dispensing residual ethanol to waste {TROUGH_WASTE}...")
        await lh.dispense(
            [trough[TROUGH_WASTE][0]] * 8,
            vols=vols,
            liquid_height=P50_WASTE_DSP_HEIGHT,
            offsets=P50_WASTE_DSP_OFFSETS,
            blow_out_air_volume=[P50_RESIDUAL_BLOWOUT_AIR_VOLUME] * 8,
        )
    finally:
        await finish_tips(lh, discard_tips, "p50")


async def run_action(lh: LiquidHandler, r: Dict[str, object], action: CleanupAction, discard_tips: bool, tip_col: int):
    print(f"\n=== {action.mode.upper()}: {action.label} ===")
    if action.kind == "add":
        if action.source_well is None:
            raise RuntimeError("Add action missing source_well.")
        await p300_add_from_trough(lh, r, action.source_well, action.volume_ul, discard_tips, tip_col)
    elif action.kind == "remove":
        await p300_remove_to_waste(lh, r, action.volume_ul, discard_tips, tip_col)
    elif action.kind == "residual_remove_p50":
        await p50_remove_residual_ethanol_to_waste(lh, r, action.volume_ul, discard_tips, tip_col)
    else:
        raise RuntimeError(f"Unknown action kind: {action.kind}")
    print(f"SUCCESS: {action.label} dry motion completed.")


async def run_ethanol_cycle(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool):
    print("\n=== ETHANOL CYCLE DRY: add/remove wash 1 + add/remove wash 2 ===")
    await run_action(lh, r, ACTIONS["ethanol-add1-dry"], discard_tips, tip_col=1)
    await run_action(lh, r, ACTIONS["ethanol-remove1-dry"], discard_tips, tip_col=2 if discard_tips else 1)
    await run_action(lh, r, ACTIONS["ethanol-add2-dry"], discard_tips, tip_col=3 if discard_tips else 1)
    await run_action(lh, r, ACTIONS["ethanol-remove2-dry"], discard_tips, tip_col=4 if discard_tips else 1)
    print("SUCCESS: ethanol cycle dry motion completed.")


async def run_ethanol_cycle_with_residual(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool):
    print("\n=== ETHANOL CYCLE + P50 RESIDUAL REMOVE DRY ===")
    await run_ethanol_cycle(lh, r, discard_tips)
    await run_action(lh, r, ACTIONS["residual-ethanol-remove-dry"], discard_tips, tip_col=1)
    print("SUCCESS: ethanol cycle + residual p50 dry motion completed.")


async def run_all_dry(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool):
    print("\n=== ALL PCR1 CLEANUP DRY MOTIONS ===")
    sequence = [
        "beads-add-dry",
        "supernatant-remove-dry",
        "ethanol-add1-dry",
        "ethanol-remove1-dry",
        "ethanol-add2-dry",
        "ethanol-remove2-dry",
        "residual-ethanol-remove-dry",
        "elution-add-dry",
    ]
    tip_col = 1
    for mode in sequence:
        await run_action(lh, r, ACTIONS[mode], discard_tips, tip_col=tip_col)
        if discard_tips:
            tip_col += 1
    print("SUCCESS: all PCR1 cleanup dry motions completed.")


async def main():
    parser = argparse.ArgumentParser(description="PCR enrichment round 1 cleanup dry-offset/motion test: mag pos2 + trough pos3.")
    parser.add_argument(
        "--mode",
        choices=["deck"] + list(ACTIONS.keys()) + ["ethanol-cycle-dry", "ethanol-cycle-residual-dry", "all-dry"],
        default="deck",
    )
    parser.add_argument("--discard-tips", action="store_true")
    parser.add_argument("--tip-col", type=int, default=1)
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No movement or liquid handling executed.")
            return
        if args.mode == "ethanol-cycle-dry":
            await run_ethanol_cycle(lh, r, args.discard_tips)
            return
        if args.mode == "ethanol-cycle-residual-dry":
            await run_ethanol_cycle_with_residual(lh, r, args.discard_tips)
            return
        if args.mode == "all-dry":
            await run_all_dry(lh, r, args.discard_tips)
            return
        if args.mode in ACTIONS:
            await run_action(lh, r, ACTIONS[args.mode], args.discard_tips, args.tip_col)
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
