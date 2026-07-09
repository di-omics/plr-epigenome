import argparse
import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import PLT_CAR_L5AC_A00, CellTreat_96_wellplate_350ul_Fb
from pylabrobot.resources.hamilton import hamilton_96_tiprack_50uL_filter

try:
    from pylabrobot.resources.coordinate import Coordinate
except ImportError:
    from pylabrobot.resources import Coordinate


TRANSFER_VOL_UL = 12.5

SOURCE_RAIL = 35
SOURCE_POS = 1
DEST_POS = 0

TIP_RAIL = 48
TIP_POS = 1
TIP_COL = 0

SOURCE_COL = 0
DEST_COL = 0

P50_SOURCE_ASP_HEIGHT = [0.9] * 8
P50_SOURCE_ASP_OFFSETS = [Coordinate(-0.65, 3.35, 0.0)] * 8

P50_WORK_DSP_HEIGHT = [1.5] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(-0.38, 3.22, 0.0)] * 8

P50_BLOWOUT_AIR_VOLUME = 6.0


async def main():
    parser = argparse.ArgumentParser(
        description="Ampseq PCR1 half-scale first pass: source rail35 pos1 col1 -> dest rail35 pos0 col1, 12.5 uL x8, discard tips."
    )
    parser.add_argument("--mode", choices=["deck", "run"], default="deck")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning deck...")
        tip_carrier = PLT_CAR_L5AC_A00(name="rail48_p50_tip_carrier")
        lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
        p50_tips = hamilton_96_tiprack_50uL_filter(name="p50_filter_tips")
        tip_carrier[TIP_POS] = p50_tips

        plate_carrier = PLT_CAR_L5AC_A00(name="rail35_plate_carrier")
        lh.deck.assign_child_resource(plate_carrier, rails=SOURCE_RAIL)

        dest_plate = CellTreat_96_wellplate_350ul_Fb(name="dest_plate_rail35_pos0")
        source_plate = CellTreat_96_wellplate_350ul_Fb(name="source_plate_rail35_pos1")

        plate_carrier[DEST_POS] = dest_plate
        plate_carrier[SOURCE_POS] = source_plate

        rows = "ABCDEFGH"
        source_col = [source_plate[f"{row}1"][0] for row in rows]
        dest_col = [dest_plate[f"{row}1"][0] for row in rows]
        tip_col = [p50_tips[f"{row}1"][0] for row in rows]

        print("")
        print("AMPSEQ PCR1 HALF-SCALE FIRST-COLUMN LIQUID TRANSFER")
        print("")
        print("Deck:")
        print("  rail48 pos1 = p50 tips")
        print("  rail35 pos1 = source plate, col1 A-H = complete 1/2-scale PCR1 mix")
        print("  rail35 pos0 = destination PCR plate, col1 A-H empty")
        print("")
        print("Transfer:")
        print(f"  volume = {TRANSFER_VOL_UL} uL x8")
        print("  source = rail35 pos1 col1 A-H")
        print("  dest   = rail35 pos0 col1 A-H")
        print("  tips   = p50 col1")
        print("  tip behavior = DISCARD after transfer")
        print("")
        print("Geometry:")
        print(f"  source height = {P50_SOURCE_ASP_HEIGHT}")
        print(f"  source offsets = {P50_SOURCE_ASP_OFFSETS}")
        print(f"  dest height = {P50_WORK_DSP_HEIGHT}")
        print(f"  dest offsets = {P50_WORK_DSP_OFFSETS}")
        print(f"  blowout air = {P50_BLOWOUT_AIR_VOLUME} uL")
        print("")

        if args.mode == "deck":
            print("Mode deck: no movement.")
            return

        if args.confirm != "RUN_PCR1_COL1_HALFSCALE":
            raise RuntimeError("Refusing to run. Add: --confirm RUN_PCR1_COL1_HALFSCALE")

        print("Picking up p50 tip column 1...")
        await lh.pick_up_tips(tip_col)

        print("Aspirating 12.5 uL x8 from source rail35 pos1 col1...")
        await lh.aspirate(
            source_col,
            vols=[TRANSFER_VOL_UL] * 8,
            liquid_height=P50_SOURCE_ASP_HEIGHT,
            offsets=P50_SOURCE_ASP_OFFSETS,
        )

        print("Dispensing 12.5 uL x8 to destination rail35 pos0 col1 with 6 uL blowout...")
        await lh.dispense(
            dest_col,
            vols=[TRANSFER_VOL_UL] * 8,
            liquid_height=P50_WORK_DSP_HEIGHT,
            offsets=P50_WORK_DSP_OFFSETS,
            blow_out_air_volume=P50_BLOWOUT_AIR_VOLUME,
        )

        print("Discarding p50 tips...")
        await lh.discard_tips()

        print("SUCCESS: PCR1 half-scale col1 12.5 uL liquid transfer completed.")

    finally:
        print("Stopping STAR backend...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
