import argparse
import asyncio
from dataclasses import dataclass
from typing import Dict, List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.backends.hamilton.STAR_chatterbox import STARChatterboxBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import PLT_CAR_L5AC_A00, CellTreat_96_wellplate_350ul_Fb, Coordinate
import pylabrobot.resources as plr_resources

# Targeted PCR library preparation - PCR2 index/barcode master-mix addition, column 1 only
#
# Forked from 01_targeted_pcr_round1_mastermix_col1.py (verified on hardware 2026-06-15).
# This is the PCR2 (indexing PCR) front-end. It mirrors the PCR1 swap-source,
# column-1, p50 transfer geometry exactly; only the reagent identity, volume,
# and thermocycler handoff change.
#
# Full targeted PCR flow (operator reference):
#   01  PCR1 master-mix add            -> 01_targeted_pcr_round1_mastermix_col1.py
#       PCR1 thermocycler
#   ->  0.9X bead clean (anti-dimer)   -> targeted_pcr_bead_clean_ratio_col1.py --preset anti-dimer
#   ->  1:4 dilution of cleaned product   *** SEE DILUTION DECISION BELOW ***
#   02  PCR2 index master-mix add      -> THIS SCRIPT, --mode pcr2-index
#       PCR2 thermocycler
#   ->  0.65X final bead clean         -> targeted_pcr_bead_clean_ratio_col1.py --preset final
#
# *** DILUTION DECISION - VERIFY, unresolved (operator to decide at PCR2 build) ***
#   Protocol: cleaned PCR1 product is diluted 1:4 (2.5 uL cleaned product + 7.5 uL H2O
#   = 10 uL), then 2 uL of that dilution is the template for PCR2 (2 uL + 23 uL index
#   MM = 25 uL PCR2).
#   OPEN QUESTION: does the robot perform the 1:4 dilution (and the 2 uL transfer into
#   a fresh PCR2 plate) as on-deck --mode steps, or is the dilution a manual off-deck
#   step so the robot's PCR2 destination already holds 2 uL diluted template?
#   This is NOT decided. The `dilute` mode below is a deliberate stub that refuses to
#   run until the flow is chosen, so no geometry is fabricated. `pcr2-index` assumes the
#   destination col 1 ALREADY contains the PCR2 template (2 uL diluted product per well).
#
# Deck (identical to PCR1, swap-source layout):
#   rail48 pos0 = p10 tips (present for deck compatibility)
#   rail48 pos1 = p50 tips (used for PCR2 index master mix)
#   rail35 pos0 = destination/work 96WP, PCR2 plate, column 1
#   rail35 pos1 = source 96WP/strip, column 1 only (index master mix)
#
# Index layout note:
#   Source col 1 A-H may carry EIGHT DIFFERENT index master mixes (unique i7/i5 per row).
#   The per-column A1:H1 -> A1:H1 transfer is 1:1 per channel, so unique-per-row indexing
#   works with no change - each source row maps to the same destination row.
#
# PCR2 reaction design (VERIFY - placeholder volume):
#   destination well starts with 2 uL diluted PCR1 product (the PCR2 template)
#   source well contains complete PCR2 index master mix:
#     (composition is operator-defined: 2X MM + i7/i5 index primers + H2O)
#     total index MM           23.0 uL   <- VERIFY against final PCR2 recipe
#   robot adds 23.0 uL index MM -> final PCR2 volume 25.0 uL
#
# PCR2 thermocycler handoff after robot step (VERIFY - placeholder, fewer cycles than PCR1):
#   98 C 30 sec
#   N cycles (typ. 8-12): 98 C 10 sec, 60-65 C 20 sec, 72 C 20 sec   <- VERIFY cycle count/temps
#   72 C 1 min
#   10 C hold

TIP_RAIL = 48
P10_TIP_POS = 0
P50_TIP_POS = 1

LABWARE_RAIL = 35
WORK_POS = 0
SOURCE_96WP_POS = 1

SOURCE_COL = 1
DEST_COL = 1

# VERIFY: placeholder index-MM volume. Confirm against the final PCR2 recipe before any wet run.
VOL_PCR2_INDEX_MASTER_MIX = 23.0

# VERIFY: 1:4 dilution arithmetic, retained for documentation only (see dilution stub below).
VOL_DILUTION_CLEANED_PRODUCT = 2.5
VOL_DILUTION_WATER = 7.5

# Reuse the validated Bio Validation 0 / PCR1 column-1 P50 geometry verbatim.
P50_WORK_DSP_HEIGHT = [0.5] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P50_SOURCE_ASP_HEIGHT = [0.0] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P50_BLOWOUT_AIR_VOLUME = 6.0

# p10 resources defined so the deck layout stays identical to PCR1, although PCR2-index uses p50.
P10_WORK_DSP_HEIGHT = [0.5] * 8
P10_WORK_DSP_OFFSETS = [Coordinate(-0.68, 3.22, 0.0)] * 8
P10_SOURCE_ASP_HEIGHT = [0.0] * 8
P10_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8
P10_BLOWOUT_AIR_VOLUME = 7.0

POST_DISPENSE_SETTLE_SECONDS = 1.0

P10_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_10uL_filter", "hamilton_96_tiprack_10ul_filter"]
P50_TIP_FACTORY_CANDIDATES = ["hamilton_96_tiprack_50uL_filter", "hamilton_96_tiprack_50ul_filter"]


@dataclass
class Step:
    mode: str
    label: str
    volume_ul: float
    tip_type: str
    manual_prep: str
    manual_stop: str


PCR2_INDEX_STEP = Step(
    mode="pcr2-index",
    label="Targeted PCR round 2 index/barcode master mix",
    volume_ul=VOL_PCR2_INDEX_MASTER_MIX,
    tip_type="p50",
    manual_prep=(
        "Destination rail35 pos0 column 1 should already contain 2 uL diluted PCR1 product "
        "(the PCR2 template) per well. Load source rail35 pos1 column 1 with the complete PCR2 "
        "index master mix - up to eight different i7/i5 index mixes, one per A-H row, are fine "
        "because the transfer is 1:1 per channel. Recommended source loading: 33-38 uL per "
        "A-H source well for margin."
    ),
    manual_stop=(
        "seal/spin, then PCR2 thermocycler (VERIFY cycle count/temps): 98 C 30 sec; "
        "N cycles of 98 C 10 sec, 60-65 C 20 sec, 72 C 20 sec; 72 C 1 min; 10 C hold."
    ),
)


def make_resource(label: str, name: str, candidates: List[str], terms: List[str]):
    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {label} resource factory: {factory_name}")
            return factory(name=name)
    terms_lower = [term.lower() for term in terms]
    available = sorted(n for n in dir(plr_resources) if any(term in n.lower() for term in terms_lower))
    raise RuntimeError(f"Could not find factory for {label}. Tried {candidates}. Nearby: {available[:80]}")


def make_p10_tips(name: str):
    return make_resource("p10 filter tips", name, P10_TIP_FACTORY_CANDIDATES, ["tip", "10"])


def make_p50_tips(name: str):
    return make_resource("p50 filter tips", name, P50_TIP_FACTORY_CANDIDATES, ["tip", "50"])


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def assign_deck(lh: LiquidHandler) -> Dict[str, object]:
    print("Assigning Targeted PCR round 2 deck: PCR1-compatible column-1 swap-source layout...")

    tip_carrier = TIP_CAR_480_A00(name="tip_car_rail48")
    labware_carrier = PLT_CAR_L5AC_A00(name="labware_car_rail35")
    lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
    lh.deck.assign_child_resource(labware_carrier, rails=LABWARE_RAIL)

    p10_tips = make_p10_tips("r48_pos0_p10_filter_tips")
    p50_tips = make_p50_tips("r48_pos1_p50_filter_tips")
    work_plate = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos0_targeted_pcr_round2_dest_96wp")
    source_96wp = CellTreat_96_wellplate_350ul_Fb(name="rail35_pos1_targeted_pcr_round2_index_source_96wp")

    tip_carrier[P10_TIP_POS] = p10_tips
    tip_carrier[P50_TIP_POS] = p50_tips
    labware_carrier[WORK_POS] = work_plate
    labware_carrier[SOURCE_96WP_POS] = source_96wp

    print("\nDeck:")
    print("  rail48 pos0 = p10 tips, present for deck compatibility")
    print("  rail48 pos1 = p50 tips, used for PCR2 index master mix")
    print("  rail35 pos0 = destination/work 96WP, PCR2 plate, destination column 1")
    print("  rail35 pos1 = source 96WP/strip, SOURCE COLUMN 1 ONLY (index master mix)")
    print("\nPCR2 index master-mix mode:")
    print("  destination col 1 A-H starts with 2 uL diluted PCR1 product (PCR2 template)")
    print("  source col 1 A-H contains PCR2 index master mix (unique i7/i5 per row allowed)")
    print(f"  transfer = {VOL_PCR2_INDEX_MASTER_MIX} uL x8 by p50  (VERIFY volume)")
    print("\nP50 geometry (inherited from validated PCR1):")
    print(f"  P50_SOURCE_ASP_HEIGHT = {P50_SOURCE_ASP_HEIGHT}")
    print(f"  P50_SOURCE_ASP_OFFSETS = {P50_SOURCE_ASP_OFFSETS}")
    print(f"  P50_WORK_DSP_HEIGHT = {P50_WORK_DSP_HEIGHT}")
    print(f"  P50_WORK_DSP_OFFSETS = {P50_WORK_DSP_OFFSETS}")
    print(f"  P50_BLOWOUT_AIR_VOLUME = {P50_BLOWOUT_AIR_VOLUME}")

    return {
        "p10_tips": p10_tips,
        "p50_tips": p50_tips,
        "work_plate": work_plate,
        "source_96wp": source_96wp,
    }


async def finish_tips(lh: LiquidHandler, discard_tips: bool):
    if discard_tips:
        print("Discarding tips...")
        await lh.discard_tips()
    else:
        print("Returning tips to rack...")
        await lh.return_tips()


async def transfer_pcr2_index_master_mix(lh: LiquidHandler, r: Dict[str, object], discard_tips: bool, tip_col: int):
    step = PCR2_INDEX_STEP
    vols = [step.volume_ul] * 8

    tips = r["p50_tips"][f"A{tip_col}:H{tip_col}"]

    print(f"\n=== {step.mode.upper()}: {step.label} ===")
    print(f"PREP: {step.manual_prep}")
    print(f"Source rail35 pos1 col {SOURCE_COL} -> destination rail35 pos0 col {DEST_COL}")
    print(f"Volume: {step.volume_ul} uL x8  (VERIFY)")
    print(f"Tip type: p50; tip column {tip_col}; discard_tips={discard_tips}")

    await lh.pick_up_tips(tips)
    try:
        print(f"Aspirating {step.volume_ul} uL x8 from PCR2 index-MM source col {SOURCE_COL}...")
        await lh.aspirate(
            wells_for_column(r["source_96wp"], SOURCE_COL),
            vols=vols,
            liquid_height=P50_SOURCE_ASP_HEIGHT,
            offsets=P50_SOURCE_ASP_OFFSETS,
            blow_out_air_volume=[0.0] * 8,
        )

        print(f"Dispensing {step.volume_ul} uL x8 to destination col {DEST_COL} with blowout {P50_BLOWOUT_AIR_VOLUME} uL...")
        print(f"Post-dispense settle before tip return/discard: {POST_DISPENSE_SETTLE_SECONDS} sec")
        await lh.dispense(
            wells_for_column(r["work_plate"], DEST_COL),
            vols=vols,
            liquid_height=P50_WORK_DSP_HEIGHT,
            offsets=P50_WORK_DSP_OFFSETS,
            blow_out_air_volume=[P50_BLOWOUT_AIR_VOLUME] * 8,
        )
        await asyncio.sleep(POST_DISPENSE_SETTLE_SECONDS)
    finally:
        await finish_tips(lh, discard_tips)

    print(f"\nSUCCESS: {step.label} addition completed.")
    print(step.manual_stop)


async def run_dilute_stub(*_args, **_kwargs):
    # DECISION PENDING - see the dilution VERIFY block in the header.
    # The 1:4 dilution (2.5 uL cleaned product + 7.5 uL H2O) and the 2 uL transfer into a
    # fresh PCR2 plate have NOT been assigned an on-deck mechanism. Refuse rather than guess
    # geometry, plate flow, or water source.
    raise NotImplementedError(
        "dilute mode is an intentional stub. Decide first whether the 1:4 dilution + 2 uL "
        "PCR2-template transfer is on-deck (robot) or off-deck (manual). If on-deck, specify "
        "the water source (swap-source pos1 col1 vs trough), the dilution plate, and how 2 uL "
        "reaches the PCR2 plate - then build this mode with tuned geometry. Until then run "
        "pcr2-index against a destination that already holds 2 uL diluted template."
    )


def make_backend(dry: bool):
    if dry:
        print("Backend: STARChatterboxBackend (DRY - simulated, no hardware movement).")
        return STARChatterboxBackend()
    print("Backend: STARBackend (REAL hardware - human-gated).")
    return STARBackend()


async def main():
    parser = argparse.ArgumentParser(
        description="Targeted PCR round 2 index master-mix addition, column 1, PCR1-compatible swap-source deck."
    )
    parser.add_argument("--mode", choices=["deck", "dilute", "pcr2-index"], default="deck")
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Use STARChatterboxBackend (simulated, no movement). Default is real STARBackend (human-gated).",
    )
    parser.add_argument(
        "--return-tips",
        action="store_true",
        help="Return tips instead of discarding. Use for dry observation. Default is production-style discard.",
    )
    parser.add_argument(
        "--tip-col",
        type=int,
        default=1,
        help="P50 tip column to use for pcr2-index. Default: 1.",
    )
    args = parser.parse_args()

    if args.tip_col < 1 or args.tip_col > 12:
        raise ValueError("--tip-col must be 1..12")

    discard_tips = not args.return_tips

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=make_backend(args.dry), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        r = await assign_deck(lh)

        if args.mode == "deck":
            print("\nMode deck: assignment only. No liquid handling executed.")
            return

        if args.mode == "dilute":
            await run_dilute_stub(lh, r, discard_tips, tip_col=args.tip_col)
            return

        if args.mode == "pcr2-index":
            print(f"Production tip behavior: discard_tips={discard_tips}; selected p50 tip column={args.tip_col}")
            await transfer_pcr2_index_master_mix(lh, r, discard_tips, tip_col=args.tip_col)
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
