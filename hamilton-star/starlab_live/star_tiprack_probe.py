import argparse
import asyncio
from typing import List, Optional

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
import pylabrobot.resources as plr_resources

TIP_CANDIDATES = {
    "p10": [
        "hamilton_96_tiprack_10uL_filter",
        "hamilton_96_tiprack_10ul_filter",
        "hamilton_96_tiprack_10uL_filter_slim",
        "hamilton_96_tiprack_10ul_filter_slim",
        "hamilton_96_tiprack_10uL",
        "hamilton_96_tiprack_10ul",
        "HTF_L",
        "HTF_L_tiprack",
    ],
    "p50": [
        "hamilton_96_tiprack_50uL_filter",
        "hamilton_96_tiprack_50ul_filter",
        "hamilton_96_tiprack_50uL",
        "hamilton_96_tiprack_50ul",
    ],
    "p300": [
        "hamilton_96_tiprack_300uL_filter_slim",
        "hamilton_96_tiprack_300ul_filter_slim",
        "hamilton_96_tiprack_300uL_filter",
        "hamilton_96_tiprack_300ul_filter",
        "hamilton_96_tiprack_300uL",
        "hamilton_96_tiprack_300ul",
    ],
    "p1000": [
        "hamilton_96_tiprack_1000uL_filter",
        "hamilton_96_tiprack_1000ul_filter",
        "hamilton_96_tiprack_1000uL",
        "hamilton_96_tiprack_1000ul",
    ],
}


def list_tip_factories() -> None:
    names = sorted(
        n for n in dir(plr_resources)
        if any(token in n.lower() for token in ["tip", "htf", "10", "50", "300", "1000"])
    )
    print("\nInstalled-ish PyLabRobot resource names containing tip/HTF/volumes:\n")
    for n in names:
        print(n)


def parse_channels(s: Optional[str]) -> Optional[List[int]]:
    if s is None or s.strip() == "":
        return None
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def make_tiprack(tip_kind: str, name: str, factory_override: Optional[str]):
    candidates = [factory_override] if factory_override else TIP_CANDIDATES[tip_kind]
    for factory_name in candidates:
        if factory_name is None:
            continue
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using {tip_kind} tiprack factory: {factory_name}")
            return factory(name=name)
    list_tip_factories()
    raise RuntimeError(
        f"No factory found for {tip_kind}. Tried {candidates}. "
        "Use --list-factories and then pass --factory EXACT_FACTORY_NAME."
    )


def normalize_selection(selection):
    if isinstance(selection, list):
        return selection
    return [selection]


async def main():
    parser = argparse.ArgumentParser(description="Single-rack Hamilton STAR tip pickup/return probe.")
    parser.add_argument("--list-factories", action="store_true", help="Print available tip-ish PLR resource names and exit.")
    parser.add_argument("--rail", type=int, default=42, help="Tip carrier rail to assign. Default: 42.")
    parser.add_argument("--pos", type=int, default=0, help="Tip carrier site/position. Default: 0.")
    parser.add_argument("--tip", choices=["p10", "p50", "p300", "p1000"], default="p10", help="Tip type to model.")
    parser.add_argument("--factory", default=None, help="Exact PyLabRobot resource factory override.")
    parser.add_argument("--wells", default="A1", help='Tip selection, e.g. "A1" first, then "A1:H1". Default: A1.')
    parser.add_argument("--channels", default="0", help='Backend channel list, e.g. "0" for A1 or "0,1,2,3,4,5,6,7" for A1:H1. Use empty string to omit.')
    args = parser.parse_args()

    if args.list_factories:
        list_tip_factories()
        return

    use_channels = parse_channels(args.channels)

    print("Initializing STAR with skip_autoload=True...")
    print(f"Probe target: rail={args.rail}, pos={args.pos}, tip={args.tip}, wells={args.wells}, channels={use_channels}")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{args.rail}")
        lh.deck.assign_child_resource(tip_carrier, rails=args.rail)

        rack = make_tiprack(args.tip, name=f"probe_{args.tip}_tips", factory_override=args.factory)
        tip_carrier[args.pos] = rack

        tips = normalize_selection(rack[args.wells])

        print("Picking up tips...")
        if use_channels is None:
            await lh.pick_up_tips(tips)
        else:
            await lh.pick_up_tips(tips, use_channels=use_channels)

        print("Returning tips...")
        await lh.return_tips()

        print("SUCCESS: pickup/return probe completed cleanly.")

    finally:
        print("Stopping STAR backend...")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
