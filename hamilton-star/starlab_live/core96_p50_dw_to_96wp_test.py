"""
core96_p50_dw_to_96wp_test.py

Hamilton STAR / PyLabRobot 96-head p50 smoke test.

Deck:
- Rail 19, carrier pos 1: p50 96-tip rack
- Rail 26, carrier pos 1: 96DW source plate
- Rail 33, carrier pos 0: 96WP destination plate

Action:
- Pick up all 96 p50 tips using the 96 head
- Aspirate same volume from all 96 wells of rail 26 pos 1 96DW
- Dispense same volume into all 96 wells of rail 33 pos 0 96WP
- Return tips to rail 19 pos 1

Run:
    python core96_p50_dw_to_96wp_test.py

Default volume is 5 uL/well water-only.
"""

import argparse
import asyncio
import inspect

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_96_wellplate_350ul_Fb,
    hamilton_96_tiprack_50uL_filter,
    Coordinate,
)
import pylabrobot.resources as plr_resources


# -----------------------------
# Deck positions
# -----------------------------
TIP_RAIL = 19
P50_TIP_POS = 1

SOURCE_RAIL = 26
SOURCE_POS = 1

WORK_RAIL = 33
WORK_POS = 0


# -----------------------------
# Your working p50 offsets, collapsed for 96-head use
# -----------------------------
DSP_X_RIGHT_SHIFT = 0.35

P50_96HEAD_ASP_HEIGHT = 2.0
P50_96HEAD_ASP_OFFSET = Coordinate(0.20, 2.30, 0.0)

P50_96HEAD_DSP_HEIGHT = 7.0
P50_96HEAD_DSP_OFFSET = Coordinate(DSP_X_RIGHT_SHIFT, 2.45, 24.0)

BLOW_OUT_AIR_VOLUME = 0.0
FLOW_RATE = None


def make_96dw_source_plate(name: str):
    candidate_factories = [
        "nest_96_wellplate_2mL_deep",
        "nest_96_wellplate_2mL_Vb",
        "Cor_96_wellplate_2mL_Vb",
        "Cor_96_wellplate_2mL_Ub",
        "Greiner_96_wellplate_2mL_Vb",
        "Axygen_96_wellplate_2mL_Vb",
    ]

    for factory_name in candidate_factories:
        factory = getattr(plr_resources, factory_name, None)
        if factory is not None:
            print(f"Using source 96DW resource factory: {factory_name}")
            return factory(name=name)

    available_96 = sorted(
        n for n in dir(plr_resources)
        if "96" in n.lower()
        and ("deep" in n.lower() or "2ml" in n.lower() or "wellplate" in n.lower())
    )
    raise RuntimeError(
        "No known 96DW plate factory was found in this PyLabRobot install. "
        "Replace make_96dw_source_plate() with the exact calibrated 96DW resource. "
        f"Possible nearby resource names: {available_96[:80]}"
    )


def supported_call_kwargs(fn, wanted_kwargs):
    """Return only kwargs supported by this installed PLR method."""
    sig = inspect.signature(fn)
    params = sig.parameters
    accepts_var_kwargs = any(p.kind == p.VAR_KEYWORD for p in params.values())

    if accepts_var_kwargs:
        return wanted_kwargs

    return {
        key: value
        for key, value in wanted_kwargs.items()
        if key in params
    }


def require_96head_methods(lh):
    required = [
        "pick_up_tips96",
        "aspirate96",
        "dispense96",
        "return_tips96",
    ]

    missing = [name for name in required if not hasattr(lh, name)]
    if missing:
        raise RuntimeError(f"Missing 96-head methods in this PLR install: {missing}")

    print("\n96-head method signatures on this install:")
    for name in required:
        fn = getattr(lh, name)
        print(f"- {name}{inspect.signature(fn)}")


async def aspirate96_with_supported_kwargs(lh, plate, volume):
    wanted = {
        "volume": volume,
        "offset": P50_96HEAD_ASP_OFFSET,
        "liquid_height": P50_96HEAD_ASP_HEIGHT,
        "flow_rate": FLOW_RATE,
        "blow_out_air_volume": BLOW_OUT_AIR_VOLUME,
    }
    kwargs = supported_call_kwargs(lh.aspirate96, wanted)

    if "offset" not in kwargs or "liquid_height" not in kwargs:
        raise RuntimeError(
            "This PLR aspirate96() does not expose offset/liquid_height kwargs. "
            "Stopping before liquid move because we want to use the tuned offsets."
        )

    print(f"Calling aspirate96 with kwargs: {kwargs}")
    await lh.aspirate96(plate, **kwargs)


async def dispense96_with_supported_kwargs(lh, plate, volume):
    wanted = {
        "volume": volume,
        "offset": P50_96HEAD_DSP_OFFSET,
        "liquid_height": P50_96HEAD_DSP_HEIGHT,
        "flow_rate": FLOW_RATE,
        "blow_out_air_volume": BLOW_OUT_AIR_VOLUME,
    }
    kwargs = supported_call_kwargs(lh.dispense96, wanted)

    if "offset" not in kwargs or "liquid_height" not in kwargs:
        raise RuntimeError(
            "This PLR dispense96() does not expose offset/liquid_height kwargs. "
            "Stopping before dispense because we want to use the tuned offsets."
        )

    print(f"Calling dispense96 with kwargs: {kwargs}")
    await lh.dispense96(plate, **kwargs)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--volume", type=float, default=5.0)
    args = parser.parse_args()

    if args.volume <= 0:
        raise ValueError("Volume must be > 0 uL.")
    if args.volume > 50:
        raise ValueError("This is a p50-tip test. Keep volume <= 50 uL.")

    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    tips_are_on_head = False

    try:
        require_96head_methods(lh)

        print("\nAssigning deck resources...")

        tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
        source_carrier = PLT_CAR_L5AC_A00(name=f"source_car_rail{SOURCE_RAIL}")
        work_carrier = PLT_CAR_L5AC_A00(name=f"work_car_rail{WORK_RAIL}")

        lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)
        lh.deck.assign_child_resource(source_carrier, rails=SOURCE_RAIL)
        lh.deck.assign_child_resource(work_carrier, rails=WORK_RAIL)

        p50_tips = hamilton_96_tiprack_50uL_filter(name="p50_filter_tips")
        source_96dw = make_96dw_source_plate(name="source_96dw_rail26_pos1")
        work_96wp = CellTreat_96_wellplate_350ul_Fb(name="work_96wp_rail33_pos0")

        tip_carrier[P50_TIP_POS] = p50_tips
        source_carrier[SOURCE_POS] = source_96dw
        work_carrier[WORK_POS] = work_96wp

        print("\n=== 96 HEAD P50 SMOKE TEST ===")
        print(f"Tips:        rail {TIP_RAIL}, carrier pos {P50_TIP_POS}")
        print(f"Source 96DW: rail {SOURCE_RAIL}, carrier pos {SOURCE_POS}")
        print(f"Dest 96WP:   rail {WORK_RAIL}, carrier pos {WORK_POS}")
        print(f"Volume:      {args.volume} uL per well")
        print(f"Asp offset:  {P50_96HEAD_ASP_OFFSET}, height {P50_96HEAD_ASP_HEIGHT}")
        print(f"Dsp offset:  {P50_96HEAD_DSP_OFFSET}, height {P50_96HEAD_DSP_HEIGHT}")
        print("\nMake sure: water in all 96 source wells, no lids, plates seated.")

        print("\nStep 1/4: picking up all 96 p50 tips...")
        await lh.pick_up_tips96(p50_tips)
        tips_are_on_head = True

        print("Step 2/4: aspirating from rail 26 pos 1 96DW...")
        await aspirate96_with_supported_kwargs(lh, source_96dw, args.volume)

        print("Step 3/4: dispensing into rail 33 pos 0 96WP...")
        await dispense96_with_supported_kwargs(lh, work_96wp, args.volume)

        print("Step 4/4: returning 96 p50 tips to rail 19 pos 1...")
        await lh.return_tips96()
        tips_are_on_head = False

        print("\nDONE: 96-head p50 transfer completed and tips returned.")

    except Exception as e:
        print("\nERROR during 96-head test:")
        print(repr(e))
        if tips_are_on_head:
            print(
                "\nTips may still be on the 96 head. I am NOT auto-returning them "
                "after an error because they may contain liquid. Check the deck/head "
                "state before continuing."
            )
        raise

    finally:
        print("\nStopping LiquidHandler...")
        await lh.stop()
        print("Stopped.")


if __name__ == "__main__":
    asyncio.run(main())
