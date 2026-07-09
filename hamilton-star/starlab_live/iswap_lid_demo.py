import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import PLT_CAR_L5AC_A00, Cor_96_wellplate_360ul_Fb
from pylabrobot.resources.coordinate import Coordinate

# ==== TUNE THESE ====
RAIL_NUMBER = 26
CARRIER_POSITION = 0
X_NUDGE_MM = -20
LIFT_MM = 50
HOLD_SECONDS = 3
# =====================

async def main():
    print("Init STAR (skip autoload)...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)
    backend = lh.backend

    try:
        await backend.iswap_open_gripper()
    except Exception as e:
        print(f"(gripper open skipped: {e})")

    plate_carrier = PLT_CAR_L5AC_A00(name=f"plt_car_rail{RAIL_NUMBER}")
    lh.deck.assign_child_resource(plate_carrier, rails=RAIL_NUMBER)
    plate = Cor_96_wellplate_360ul_Fb(name="nest_plate", with_lid=True)
    plate_carrier[CARRIER_POSITION] = plate

    lid_loc = plate.lid.get_absolute_location()

    # Single source of truth — X, Y, Z computed ONCE
    TARGET_X = lid_loc.x + X_NUDGE_MM
    TARGET_Y = lid_loc.y
    TARGET_Z = lid_loc.z

    print(f"Target position: X={TARGET_X:.1f}, Y={TARGET_Y:.1f}, Z={TARGET_Z:.1f}")
    print(f"(Lift for hover: Z={TARGET_Z + LIFT_MM:.1f})\n")

    # === PICKUP using move_lid (this works) ===
    print("Phase 1: pickup lid (move_lid to hover position)")
    pickup_target = Coordinate(x=TARGET_X, y=TARGET_Y, z=TARGET_Z + LIFT_MM)
    await lh.move_lid(plate.lid, pickup_target)
    print(f"Holding {HOLD_SECONDS}s...\n")
    await asyncio.sleep(HOLD_SECONDS)

    # === DROP using raw iSWAP commands — forced exact X,Y,Z ===
    print("Phase 2: drop lid at EXACT same XYZ using raw iSWAP commands")
    # Stay at lift height, lock X and Y to EXACTLY pickup values
    await backend.move_iswap_x(TARGET_X)
    await backend.move_iswap_y(TARGET_Y)
    # Descend to exact grip height (same as lid bottom)
    await backend.move_iswap_z(TARGET_Z)
    print("At drop Z. Opening gripper to release...")
    await backend.iswap_open_gripper()
    await asyncio.sleep(1)
    # Back up
    await backend.move_iswap_z(TARGET_Z + LIFT_MM)
    print("Lid released, iSWAP retracted.\n")

    await backend.park_iswap()
    await lh.stop()
    print("Demo complete.")

asyncio.run(main())
