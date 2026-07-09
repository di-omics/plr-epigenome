import argparse
import asyncio
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# -----------------------------------------------------------------------------
# whole-genome sequencing V2 Phase 2 smoke test: DNA Prep Master Mix only
#
# Purpose:
# - One isolated live/bioval step before building the rest.
# - Transfer 3.0 uL DNA Prep Master Mix from source 96WP rail35 pos1 col 1
#   into destination/work 96WP rail35 pos0 col 1.
# - Return tips, do not discard.
# - Stop after this transfer so the plate can be manually sealed/spun/vortexed
#   and moved to the thermocycler for DNAPREP.
#
# Biology context:
# - Destination/work plate column 1 should already contain WGA product + elution
#   buffer at 3.0 uL total per well.
# - Source/chilled plate column 1 contains DNA Prep Master Mix.
# - This script adds 3.0 uL DNA Prep Master Mix to A1:H1.
#
# Deck:
# - rail48 pos0 = p10 tips
# - rail35 pos0 = destination/work 96WP
# - rail35 pos1 = chilled source 96WP
#
# Geometry tweak in this build:
# - Y restored to known-good 3.35 after channel-spacing error at 3.20
# - Z/liquid height lowered slightly: 7.0 -> 6.5
# KEY geometry inherited from x-left truth-set scaffold:
# - Source pos1 is a 96WP, not a 96DW.
# - Source pos1 uses the SAME XY offsets as destination/work pos0.
# - Both source aspirate and destination dispense use x-left offset:
#   Coordinate(-0.35, 3.35, 0.0)
# -----------------------------------------------------------------------------

TIP_RAIL = 48
P10_TIP_POS = 0

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1

SOURCE_COL = 1
DEST_COL = 1
DNAPREP_MM_VOLUME_UL = 3.0

WORK_96WP_DSP_HEIGHT = [6.3] * 8
WORK_96WP_DSP_OFFSETS = [Coordinate(-0.35, 3.35, 0.0)] * 8

SOURCE_96WP_ASP_HEIGHT = [6.3] * 8
SOURCE_96WP_ASP_OFFSETS = WORK_96WP_DSP_OFFSETS

P10_BLOWOUT_AIR_VOLUME = 5.0

P10_TIP_FACTORY_CANDIDATES = [
    "hamilton_96_tiprack_10uL_filter",
    "hamilton_96_tiprack_10ul_filter",
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


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning whole-genome sequencing V2 DNAPREP-only smoke-test deck...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_work_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_chilled_source_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96WP_POS] = source_96wp

    print("\nDeck resources:")
    print("  rail48 pos0 = p10 tips")
    print("  rail35 pos0 = destination/work 96WP")
    print("  rail35 pos1 = CHILLED SOURCE 96WP")

    print("\nDNAPREP-only transfer:")
    print(f"  source pos1 col {SOURCE_COL} -> destination pos0 col {DEST_COL}")
    print(f"  volume = {DNAPREP_MM_VOLUME_UL} uL x8")

    print("\nShared 96WP geometry:")
    print(f"  WORK_96WP_DSP_HEIGHT = {WORK_96WP_DSP_HEIGHT}")
    print(f"  WORK_96WP_DSP_OFFSETS = {WORK_96WP_DSP_OFFSETS}")
    print(f"  SOURCE_96WP_ASP_HEIGHT = {SOURCE_96WP_ASP_HEIGHT}")
    print(f"  SOURCE_96WP_ASP_OFFSETS = {SOURCE_96WP_ASP_OFFSETS}")
    print("  Source pos1 intentionally uses same plate definition and XY offsets as work pos0.")

    print("\nTip behavior:")
    print("  p10 tips A1:H1 are used and returned to rack.")
    print(f"  P10_BLOWOUT_AIR_VOLUME = {P10_BLOWOUT_AIR_VOLUME}")

    return {
        "p10_tips": p10_tips,
        "work_plate": work_plate,
        "source_96wp": source_96wp,
    }


async def run_dnaprep_addition(lh: LiquidHandler, r: Dict[str, object]):
    vols = [DNAPREP_MM_VOLUME_UL] * 8

    print("\n=== DNAPREP MASTER MIX ADDITION ONLY ===")
    print("Picking up p10 tips A1:H1...")
    await lh.pick_up_tips(r["p10_tips"]["A1:H1"])

    try:
        print(f"Aspirating {DNAPREP_MM_VOLUME_UL} uL x8 from source 96WP rail35 pos1 col {SOURCE_COL}...")
        await lh.aspirate(
            r["source_96wp"][f"A{SOURCE_COL}:H{SOURCE_COL}"],
            vols=vols,
            liquid_height=SOURCE_96WP_ASP_HEIGHT,
            offsets=SOURCE_96WP_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )

        print(f"Dispensing {DNAPREP_MM_VOLUME_UL} uL x8 to destination/work 96WP rail35 pos0 col {DEST_COL}...")
        print(f"Using p10 blowout {P10_BLOWOUT_AIR_VOLUME} uL. No delay_time keyword; this backend ignored it.")
        await lh.dispense(
            wells_for_column(r["work_plate"], DEST_COL),
            vols=vols,
            liquid_height=WORK_96WP_DSP_HEIGHT,
            offsets=WORK_96WP_DSP_OFFSETS,
            blow_out_air_volume=[P10_BLOWOUT_AIR_VOLUME] * 8,
        )

    finally:
        print("Returning p10 tips to rack...")
        await lh.return_tips()

    print("\nSUCCESS: DNAPREP-only 3 uL addition completed.")
    print("Stop here: manually seal, spin/vortex/spin as needed, and run DNAPREP thermocycler program.")


async def main():
    parser = argparse.ArgumentParser(description="whole-genome sequencing V2 DNAPREP-only 3 uL addition smoke test.")
    parser.add_argument("--mode", choices=["deck", "run"], default="run")
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No movement or liquid handling executed.")
            return

        await run_dnaprep_addition(lh, r)

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
