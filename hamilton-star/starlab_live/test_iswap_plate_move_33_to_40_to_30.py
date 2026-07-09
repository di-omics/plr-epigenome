import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
)

# ---------------------------------------------------------------------
# iSWAP plate move test - current ResolveDNA deck
#
# Goal:
#   Move one 96WP by iSWAP:
#     rail 33 pos 0 -> rail 40 pos 0
#     rail 40 pos 0 -> rail 30 pos 0
#
# Assumptions:
#   - rail 33 pos 0 starts with the physical 96WP.
#   - rail 40 pos 0 is empty.
#   - rail 30 pos 0 is empty.
#   - No tips are on channels.
#   - No iSWAP-held resource at startup.
#
# Notes:
#   - Uses lh.setup(skip_autoload=True).
#   - Uses slow_iswap() for safer/smoother first validation.
#   - This is a movement-only test; no liquid handling.
# ---------------------------------------------------------------------

START_RAIL = 33
START_POS = 0

CLEANUP_RAIL = 40
CLEANUP_POS = 0

FINAL_RAIL = 30
FINAL_POS = 0


async def main():
    print("Initializing STAR for iSWAP plate move test...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning carriers/resources...")

        start_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{START_RAIL}")
        cleanup_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{CLEANUP_RAIL}")
        final_carrier = PLT_CAR_L5AC_A00(name=f"plate_car_rail{FINAL_RAIL}")

        lh.deck.assign_child_resource(start_carrier, rails=START_RAIL)
        lh.deck.assign_child_resource(cleanup_carrier, rails=CLEANUP_RAIL)
        lh.deck.assign_child_resource(final_carrier, rails=FINAL_RAIL)

        # Same plate type used in the current ResolveDNA LH protocol.
        work_plate = CellTreat_96_wellplate_350ul_Fb(name="resolve_work_plate")

        # Physical starting state: plate is on rail 33 pos 0.
        start_carrier[START_POS] = work_plate

        print(f"Step 1: moving plate rail {START_RAIL} pos {START_POS} -> rail {CLEANUP_RAIL} pos {CLEANUP_POS}...")
        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, cleanup_carrier[CLEANUP_POS])

        print(f"Step 2: moving plate rail {CLEANUP_RAIL} pos {CLEANUP_POS} -> rail {FINAL_RAIL} pos {FINAL_POS}...")
        async with lh.backend.slow_iswap():
            await lh.move_plate(work_plate, final_carrier[FINAL_POS])

        print("SUCCESS: iSWAP plate move test completed.")
        print(f"Final expected physical location: rail {FINAL_RAIL} pos {FINAL_POS}")

    finally:
        print("Parking / stopping...")
        try:
            await lh.backend.park_iswap()
        except Exception as e:
            print(f"park_iswap warning: {e!r}")
        await lh.stop()
        print("Done.")


asyncio.run(main())
