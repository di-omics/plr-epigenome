import asyncio
from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck
from pylabrobot.resources import PLT_CAR_L5AC_A00, Cor_96_wellplate_360ul_Fb

RAIL_NUMBER = 26
PICKUP_POSITION = 0
DROP_POSITION = 1

async def main():
    print("Initializing STAR...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    plate_carrier = PLT_CAR_L5AC_A00(name=f"plt_car_rail{RAIL_NUMBER}")
    lh.deck.assign_child_resource(plate_carrier, rails=RAIL_NUMBER)

    pickup_plate = Cor_96_wellplate_360ul_Fb(name="plate_pickup", with_lid=True)
    drop_plate = Cor_96_wellplate_360ul_Fb(name="plate_drop", with_lid=False)

    plate_carrier[PICKUP_POSITION] = pickup_plate
    plate_carrier[DROP_POSITION] = drop_plate

    print(f"Moving lid from pos{PICKUP_POSITION} to pos{DROP_POSITION}...")
    async with lh.backend.slow_iswap():
        await lh.move_lid(pickup_plate.lid, drop_plate)

    print("Parking / stopping...")
    await lh.stop()
    print("Done.")

asyncio.run(main())
