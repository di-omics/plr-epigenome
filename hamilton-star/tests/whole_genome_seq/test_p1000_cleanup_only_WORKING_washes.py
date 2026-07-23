import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    hamilton_96_tiprack_1000uL_filter,
    Coordinate,
)

# P1000 cleanup-only validation.
# Tests only rail 26 pos 2 trough -> rail 40 pos 0 96WP.
# Mix is intentionally OFF for now.
# Rail 40 dispense uses the same high-Z 96WP-style offset as the rail 33 work plate.

TIP_RAIL = 19
P1000_TIP_POS = 0

SOURCE_RAIL = 26
TROUGH_POS = 2

MAG_RAIL = 40
MAG_POS = 0

DEST_COLUMNS = [1]

TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"

VOL_BEADS = 30
VOL_ETOH = 200
VOL_ELUTION = 42

DSP_X_RIGHT_SHIFT = 0.35

P1000_ASP_HEIGHT = [1.5] * 8
P1000_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P1000_MAG_DSP_HEIGHT = [8.0] * 8
P1000_MAG_DSP_OFFSETS = [Coordinate(DSP_X_RIGHT_SHIFT, 2.45, 27.0)] * 8


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def transfer_from_trough(lh, source_well, target_wells, vol, label):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL x 8 from trough {label}...")
    await lh.aspirate(
        [source_well] * 8,
        vols=volumes,
        liquid_height=P1000_ASP_HEIGHT,
        offsets=P1000_ASP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )

    print("Dispensing into rail 40 column without mix...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=P1000_MAG_DSP_HEIGHT,
        offsets=P1000_MAG_DSP_OFFSETS,
        blow_out_air_volume=[0.0] * 8,
    )


async def main():
    print("Initializing STAR for p1000 cleanup-only test...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning deck resources...")
        tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
        lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

        source_carrier = PLT_CAR_L5AC_A00(name=f"source_car_rail{SOURCE_RAIL}")
        lh.deck.assign_child_resource(source_carrier, rails=SOURCE_RAIL)

        mag_carrier = PLT_CAR_L5AC_A00(name=f"mag_car_rail{MAG_RAIL}")
        lh.deck.assign_child_resource(mag_carrier, rails=MAG_RAIL)

        p1000_tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
        trough = CellTreat_12_troughplate_15000ul_Vb(name="bulk_liquid_trough")
        mag_plate = CellTreat_96_wellplate_350ul_Fb(name="mag_cleanup_96wp")

        tip_carrier[P1000_TIP_POS] = p1000_tips
        source_carrier[TROUGH_POS] = trough
        mag_carrier[MAG_POS] = mag_plate

        print("Picking up p1000 tips from rail 19 pos 0 A1:H1...")
        await lh.pick_up_tips(p1000_tips["A1:H1"])

        targets = wells_for_column(mag_plate, 1)

        await transfer_from_trough(lh, trough[TROUGH_BEADS][0], targets, VOL_BEADS, f"{TROUGH_BEADS} (SPRI cleanup beads)")
        await transfer_from_trough(lh, trough[TROUGH_ETOH1][0], targets, VOL_ETOH, f"{TROUGH_ETOH1} (80% EtOH wash 1)")
        await transfer_from_trough(lh, trough[TROUGH_ETOH2][0], targets, VOL_ETOH, f"{TROUGH_ETOH2} (80% EtOH wash 2)")
        await transfer_from_trough(lh, trough[TROUGH_ELUTION][0], targets, VOL_ELUTION, f"{TROUGH_ELUTION} (Elution Buffer)")

        print("Returning p1000 tips...")
        await lh.return_tips()
        print("SUCCESS: p1000 cleanup-only test completed.")

    finally:
        print("Stopping...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
