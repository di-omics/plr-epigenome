import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import PLT_CAR_L5AC_A00, Cor_96_wellplate_360ul_Fb

RAIL_NUMBER = 26
PICKUP_POSITION = 0
DROP_POSITION = 1
X_NUDGE_MM = -77
Y_NUDGE_MM = 180

# Gripper settings (in 0.1mm units — multiply mm by 10)
OPEN_GRIPPER_POS = 860    # 86.0mm (gripper open position before descent)
PLATE_WIDTH = 780         # 78.0mm (target plate/lid width — tighter than 80 = narrower grip)
PLATE_WIDTH_TOL = 20      # 2.0mm tolerance
GRIP_STRENGTH = 7

async def main():
    print("Init STAR (skip autoload)...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)
    backend = lh.backend

    plate_carrier = PLT_CAR_L5AC_A00(name=f"plt_car_rail{RAIL_NUMBER}")
    lh.deck.assign_child_resource(plate_carrier, rails=RAIL_NUMBER)
    pickup_plate = Cor_96_wellplate_360ul_Fb(name="plate_pickup", with_lid=True)
    plate_carrier[PICKUP_POSITION] = pickup_plate
    drop_plate = Cor_96_wellplate_360ul_Fb(name="plate_drop", with_lid=False)
    plate_carrier[DROP_POSITION] = drop_plate

    pickup_loc = pickup_plate.lid.get_absolute_location()
    drop_loc = drop_plate.get_absolute_location()

    # Compute targets in 0.1mm firmware units
    PICKUP_X = int(round((pickup_loc.x + X_NUDGE_MM) * 10))
    PICKUP_Y = int(round((pickup_loc.y + Y_NUDGE_MM) * 10))
    PICKUP_Z = int(round(pickup_loc.z * 10))
    DROP_X = int(round((drop_loc.x + X_NUDGE_MM) * 10))
    DROP_Y = int(round((drop_loc.y + Y_NUDGE_MM) * 10))
    DROP_Z = int(round(drop_loc.z * 10))

    print(f"PICKUP (0.1mm units): X={PICKUP_X} Y={PICKUP_Y} Z={PICKUP_Z}")
    print(f"DROP   (0.1mm units): X={DROP_X} Y={DROP_Y} Z={DROP_Z}\n")

    print("Calling iswap_get_plate (pickup lid from pos 0)...")
    await backend.iswap_get_plate(
        x_position=PICKUP_X,
        x_direction=0,
        y_position=PICKUP_Y,
        y_direction=0,
        z_position=PICKUP_Z,
        z_direction=0,
        grip_direction=1,   # 1 = from front
        grip_strength=GRIP_STRENGTH,
        open_gripper_position=OPEN_GRIPPER_POS,
        plate_width=PLATE_WIDTH,
        plate_width_tolerance=PLATE_WIDTH_TOL,
    )
    print("Lid picked up!\n")
    await asyncio.sleep(2)

    print("Calling iswap_put_plate (drop lid at pos 1)...")
    await backend.iswap_put_plate(
        x_position=DROP_X,
        x_direction=0,
        y_position=DROP_Y,
        y_direction=0,
        z_position=DROP_Z,
        z_direction=0,
        grip_direction=1,
        open_gripper_position=OPEN_GRIPPER_POS,
    )
    print("Lid placed!\n")

    await backend.park_iswap()
    await lh.stop()
    print("Done.")

asyncio.run(main())
