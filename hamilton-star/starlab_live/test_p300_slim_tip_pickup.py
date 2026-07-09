import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
import pylabrobot.resources as plr_resources

TIP_RAIL = 19
P300_TIP_POS = 2


def make_p300_slim_tiprack(name: str):
    # Try likely p300 filter slim Hamilton names first.
    candidates = [
        "hamilton_96_tiprack_300uL_filter_slim",
    ]

    for factory_name in candidates:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using p300 filter slim tiprack resource factory: {factory_name}")
            return factory(name=name)

    available = sorted(
        n for n in dir(plr_resources)
        if "tip" in n.lower() or "htf" in n.lower() or "300" in n.lower()
    )
    raise RuntimeError(
        "Could not find a p300 filter slim tiprack factory in this PyLabRobot install. "
        f"Nearby resource names: {available[:120]}"
    )


async def main():
    print("Initializing STAR for p300 filter slim tip pickup test...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning tip carrier...")
        tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
        lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

        p300_tips = make_p300_slim_tiprack(name="p300_filter_slim_tips")
        tip_carrier[P300_TIP_POS] = p300_tips

        print(f"Picking up p300 filter slim tips from rail {TIP_RAIL} pos {P300_TIP_POS} A1:H1...")
        await lh.pick_up_tips(p300_tips["A1:H1"])

        print("Returning p300 filter slim tips...")
        await lh.return_tips()

        print("SUCCESS: p300 filter slim tip pickup/return test completed.")

    finally:
        print("Stopping...")
        await lh.stop()
        print("Done.")


asyncio.run(main())
