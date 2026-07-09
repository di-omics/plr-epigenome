import asyncio

from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck


# Known-good cleanup dropoff target:
# Coordinate(004.000, 012.000, 126.150) mm
# Low-level iSWAP args use 0.1 mm units.
X_POS = 40
Y_POS = 120
Z_POS = 1262

GRIP_DIRECTION = 1
OPEN_GRIPPER_POSITION = 860


async def main():
    print("Creating STAR backend with deck...")
    backend = STARBackend()
    backend.deck = STARDeck()   # CRITICAL: fixes 'Deck not set'

    try:
        print("Connecting backend...")
        try:
            await backend.setup(skip_autoload=True)
            print("Backend setup completed.")
        except Exception as e:
            print(f"backend.setup failed/warned: {e!r}")
            print("Continuing anyway in case USB connection is open...")

        print("ONE ACTION: put currently held iSWAP plate down at rail 40 pos 0.")
        print(f"x_position={X_POS}, y_position={Y_POS}, z_position={Z_POS}")
        print(f"grip_direction={GRIP_DIRECTION}, open_gripper_position={OPEN_GRIPPER_POSITION}")

        await backend.iswap_put_plate(
            x_position=X_POS,
            x_direction=0,
            y_position=Y_POS,
            y_direction=0,
            z_position=Z_POS,
            z_direction=0,
            grip_direction=GRIP_DIRECTION,
            minimum_traverse_height_at_beginning_of_a_command=3600,
            z_position_at_the_command_end=3600,
            open_gripper_position=OPEN_GRIPPER_POSITION,
            collision_control_level=1,
            acceleration_index_high_acc=2,
            acceleration_index_low_acc=1,
            iswap_fold_up_sequence_at_the_end_of_process=False,
        )

        print("DROP COMMAND COMPLETED. Check plate at rail 40 pos 0.")

    finally:
        print("Closing backend connection...")
        try:
            await backend.stop()
        except Exception as e:
            print(f"backend.stop warning: {e!r}")
        print("Done.")


asyncio.run(main())
