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
from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# PCR enrichment operator-parameterized bead clean - column 1
#
# This retains the validated mag(pos2)+trough(pos3) deck and hand-tuned p300/p50
# geometry. Runtime method values come from the operator-approved local profile.
#
# Deck (identical to the 04 cleanup):
#   rail48 pos1 = p50 tips (residual ethanol removal)
#   rail48 pos2 = p300 tips
#   rail35 pos2 = magnetic rack / cleanup 96WP, column 1 only
#   rail35 pos3 = 12-well reservoir/trough
#
# Reservoir map:
#   A1 = cleanup beads     A2 = wash 1             A3 = wash 2
#   A4 = elution buffer    A12 = waste
#
# Tip behavior (PRODUCTION module, unlike the 04 dry-offset test):
#   DISCARD tips by default. Pass --return-tips only for chatterbox dry / water observation.
#
# CHATTERBOX NOTE (known PLR 0.2.1 quirk, not a defect):
#   The add modes aspirate one trough well broadcast to 8 channels, which trips PLR's
#   _position_channels_wide check in the chatterbox backend only. Expect beads-add /
#   ethanol-add* / elution-add to fail under --dry at the trough aspirate; they pass on
#   real hardware. Remove modes (plate -> waste) aspirate per-well and dry-run cleanly.

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

# --- Operator method parameters ---------------------------------------------
BEAD_RATIO = required_positive("pcr_enrichment.cleanup.bead_ratio")
INPUT_VOLUME_UL = required_positive("pcr_enrichment.cleanup.input_volume_ul")
VOL_BEADS = required_positive("pcr_enrichment.cleanup.bead_volume_ul")
VOL_SUPERNATANT_REMOVE = required_positive("pcr_enrichment.cleanup.supernatant_remove_ul")
VOL_ETHANOL_ADD = required_positive("pcr_enrichment.cleanup.wash_add_ul")
VOL_ETHANOL_REMOVE = required_positive("pcr_enrichment.cleanup.wash_remove_ul")
VOL_ELUTION = required_positive("pcr_enrichment.cleanup.elution_ul")
VOL_RESIDUAL_ETHANOL_REMOVE = required_positive("pcr_enrichment.cleanup.residual_remove_ul")
WASH_INCUBATION_SECONDS = required_nonnegative("pcr_enrichment.cleanup.wash_incubation_seconds")
P300_MAX_VOL_UL = 300.0

# --- Geometry inherited verbatim from the validated 04 cleanup --------------
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

P50_MAG_RESIDUAL_ASP_HEIGHT = [3.3] * 8
P50_MAG_RESIDUAL_ASP_OFFSETS = [Coordinate(-0.72, 3.35, 0.0)] * 8
P50_WASTE_DSP_HEIGHT = [8.0] * 8
P50_WASTE_DSP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8
P50_RESIDUAL_BLOWOUT_AIR_VOLUME = 2.0

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
class CleanupAction:
    mode: str
    label: str
    kind: str
    source_well: Optional[str]
    volume_ul: float


def build_actions() -> Dict[str, CleanupAction]:
    return {
        "beads-add": CleanupAction("beads-add", "Add cleanup beads (operator-profile volume)", "add", TROUGH_BEADS, VOL_BEADS),
        "supernatant-remove": CleanupAction(
            "supernatant-remove", "Remove post-bind supernatant to waste", "remove", None, VOL_SUPERNATANT_REMOVE
        ),
        "ethanol-add1": CleanupAction("ethanol-add1", "Add ethanol wash 1", "add", TROUGH_ETOH1, VOL_ETHANOL_ADD),
        "ethanol-remove1": CleanupAction(
            "ethanol-remove1", "Remove ethanol wash 1 to waste", "remove", None, VOL_ETHANOL_REMOVE
        ),
        "ethanol-add2": CleanupAction("ethanol-add2", "Add ethanol wash 2", "add", TROUGH_ETOH2, VOL_ETHANOL_ADD),
        "ethanol-remove2": CleanupAction(
            "ethanol-remove2", "Remove ethanol wash 2 to waste", "remove", None, VOL_ETHANOL_REMOVE
        ),
        "residual-ethanol-remove": CleanupAction(
            "residual-ethanol-remove", "Remove residual/dead ethanol with p50 to waste",
            "residual_remove_p50", None, VOL_RESIDUAL_ETHANOL_REMOVE,
        ),
        "elution-add": CleanupAction("elution-add", "Add elution buffer", "add", TROUGH_ELUTION, VOL_ELUTION),
    }


ALL_DRY_SEQUENCE = [
    "beads-add",
    "supernatant-remove",
    "ethanol-add1",
    "ethanol-remove1",
    "ethanol-add2",
    "ethanol-remove2",
    "residual-ethanol-remove",
    "elution-add",
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


def make_p50_tips(name: str):
    return make_resource("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES, ["tip", "50"])


def make_p300_tips(name: str):
    return make_resource("p300 filter tips", name, P300_TIP_FACTORY_CANDIDATES, ["tip", "300"])


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning PCR enrichment bead-clean deck: mag pos2 + trough pos3...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    p300_tips = make_p300_tips("r48_pos2_p300_filter_tips")
    mag_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos2_mag_cleanup_96wp")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="rail35_pos3_12w_reservoir")

    tip_carrier[P50_TIP_POS] = p50_tips
    tip_carrier[P300_TIP_POS] = p300_tips
    labware_carrier[MAG_POS] = mag_plate
    labware_carrier[TROUGH_POS] = trough

    print("\nDeck:")
    print("  rail48 pos1 = p50 tips for residual ethanol removal")
    print("  rail48 pos2 = p300 tips")
    print("  rail35 pos2 = magnetic rack / cleanup plate, column 1 only")
    print("  rail35 pos3 = 12-well reservoir/trough")
    print("\nReservoir map:")
    print(f"  {TROUGH_BEADS} = cleanup beads")
    print(f"  {TROUGH_ETOH1} = ethanol wash 1   {TROUGH_ETOH2} = ethanol wash 2")
    print(f"  {TROUGH_ELUTION} = elution buffer   {TROUGH_WASTE} = waste")
    print("\nOperator-profile cleanup values:")
    print(f"  ratio = {BEAD_RATIO}; input volume = {INPUT_VOLUME_UL} uL")
    print(f"  beads = {VOL_BEADS} uL x8")
    print(f"  supernatant removal = {VOL_SUPERNATANT_REMOVE} uL x8")
    print(f"  ethanol add/remove = {VOL_ETHANOL_ADD}/{VOL_ETHANOL_REMOVE} uL ; elution = {VOL_ELUTION} uL")

    return {"p50_tips": p50_tips, "p300_tips": p300_tips, "mag_plate": mag_plate, "trough": trough}


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips...")
        await lh.discard_tips()
    else:
        print("Returning tips...")
        await lh.return_tips()


async def p300_add_from_trough(lh, r, source_well_name, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    trough = r["trough"]
    plate = r["mag_plate"]

    print(f"\nP300 ADD: reservoir {source_well_name} -> mag pos2 plate col {DEST_COL}; {volume_ul} uL x8")
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
        await finish_tips(lh, discard_tips)


async def p300_remove_to_waste(lh, r, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    trough = r["trough"]
    plate = r["mag_plate"]

    print(f"\nP300 REMOVE: mag pos2 plate col {DEST_COL} -> waste {TROUGH_WASTE}; {volume_ul} uL x8")
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
        await finish_tips(lh, discard_tips)


async def p50_remove_residual_ethanol_to_waste(lh, r, volume_ul, discard_tips, tip_col):
    vols = [volume_ul] * 8
    trough = r["trough"]
    plate = r["mag_plate"]

    print(f"\nP50 RESIDUAL ETHANOL REMOVE: mag pos2 plate col {DEST_COL} -> waste {TROUGH_WASTE}; {volume_ul} uL x8")
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
        await finish_tips(lh, discard_tips)


async def run_action(lh, r, action: CleanupAction, discard_tips: bool, tip_col: int):
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
    print(f"SUCCESS: {action.label} completed.")


async def run_all(lh, r, actions: Dict[str, CleanupAction], discard_tips: bool):
    print("\n=== FULL OPERATOR-CONFIGURED BEAD-CLEAN SEQUENCE ===")
    tip_col = 1
    for mode in ALL_DRY_SEQUENCE:
        await run_action(lh, r, actions[mode], discard_tips, tip_col=tip_col)
        if mode in {"ethanol-add1", "ethanol-add2"}:
            print(
                f"Operator-profile wash incubation: {WASH_INCUBATION_SECONDS} sec "
                "before the corresponding removal."
            )
            await asyncio.sleep(WASH_INCUBATION_SECONDS)
        if discard_tips:
            tip_col += 1
    print("SUCCESS: full operator-configured bead-clean sequence completed.")


def make_backend(dry: bool):
    if dry:
        print("Backend: STARChatterboxBackend (DRY - simulated, no hardware movement).")
        return STARChatterboxBackend()
    print("Backend: STARBackend (REAL hardware - human-gated).")
    return STARBackend()


async def main():
    parser = argparse.ArgumentParser(description="PCR enrichment operator-parameterized bead clean: mag pos2 + trough pos3.")
    parser.add_argument(
        "--mode",
        choices=["deck"] + ALL_DRY_SEQUENCE + ["all"],
        default="deck",
    )
    parser.add_argument("--dry", action="store_true",
                        help="Use STARChatterboxBackend (simulated). Default is real STARBackend (human-gated).")
    parser.add_argument("--return-tips", action="store_true",
                        help="Return tips instead of discarding. Dry/observation only. Default is production discard.")
    parser.add_argument("--tip-col", type=int, default=1)
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

    if VOL_SUPERNATANT_REMOVE > P300_MAX_VOL_UL:
        raise ValueError(
            f"Configured supernatant removal {VOL_SUPERNATANT_REMOVE} uL exceeds "
            f"p300 max {P300_MAX_VOL_UL} uL; split the removal or use a larger tip."
        )

    actions = build_actions()
    discard_tips = not args.return_tips

    print(
        "Operator-configured bead clean: "
        f"ratio={BEAD_RATIO}, input_vol={INPUT_VOLUME_UL} uL, "
        f"beads={VOL_BEADS} uL, supernatant_remove={VOL_SUPERNATANT_REMOVE} uL"
    )
    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=make_backend(args.dry), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No movement or liquid handling executed.")
            return

        if args.mode == "all":
            await run_all(lh, r, actions, discard_tips)
            return

        if args.mode in actions:
            await run_action(lh, r, actions[args.mode], discard_tips, args.tip_col)
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
