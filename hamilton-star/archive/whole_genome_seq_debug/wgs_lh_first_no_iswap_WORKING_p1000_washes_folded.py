import asyncio
from typing import List

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.liquid_handling.standard import Mix
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    hamilton_96_tiprack_1000uL_filter,
    hamilton_96_tiprack_50uL_filter,
    Coordinate,
)
import pylabrobot.resources as plr_resources

# ---------------------------------------------------------------------
# WGS preparation (PTA) - Hamilton STAR / PyLabRobot
# LH-first scaffold, before adding iSWAP movements.
#
# Deck intent from Di:
# - Reagent/source liquid starts on rail 26, carrier position 1, 96DW.
# - Beads/ethanol/elution are in reservoir/trough on rail 26, carrier position 2.
# - Working 96-well plate is on rail 33, carrier position 0, 96WP.
# - All bead/ethanol cleanup liquid handling happens on rail 40, position 0.
# - iSWAP movements will be added after LH is validated.
# - 96WP dispense X offsets are shifted slightly right to avoid grabbing/lifting the plate.
# - Mix is currently disabled after overnight troubleshooting; re-enable bead/elution mix after geometry validation.
#
# Safety:
# - Uses lh.setup(skip_autoload=True).
# - Keep the deck clear before init/homing.
# - This script does not implement iSWAP yet.
#
# First-pass assumptions:
# - 8 samples in column 1 only. Extend DEST_COLUMNS for more columns.
# - Reagents are laid out in the 96DW source plate as defined below.
# - Adapter transfer is implemented as source column -> destination column,
#   but you must verify the UDI map before using on real samples.
# - Cleanup aspiration/removal steps are TODO stubs until waste handling and
#   bead-safe aspiration geometry are tuned.
# ---------------------------------------------------------------------

TIP_RAIL = 19
P1000_TIP_POS = 0
P50_TIP_POS = 1

SOURCE_RAIL = 26
SOURCE_POS = 1  # 96DW/source reagent plate at rail 26, position 1
TROUGH_POS = 2  # reservoir/trough at rail 26, position 2

WORK_RAIL = 33
WORK_POS = 0    # user-specified: 96WP at rail 33, position 0

MAG_RAIL = 40
MAG_POS = 0     # user-specified: cleanup/magnet at rail 40, position 0

DEST_COLUMNS = [1]  # v1: A1:H1 only. Extend to [1, 2, ...] after validation.

# Dispense/mix tuning.
# Positive X moves the dispense position slightly right in the 96WP.
# Increase/decrease by small increments after dry/water validation.
DSP_X_RIGHT_SHIFT = 0.35
MIX_REPETITIONS = 3
MIX_FLOW_RATE = 100



# -----------------------------
# Resource helpers
# -----------------------------
def make_96dw_source_plate(name: str):
    """Create a 96-deepwell plate resource if available in this PLR install.

    Different PyLabRobot versions expose deepwell resources under different
    factory names. This helper tries common names and fails loudly if none
    are present, so the operator can swap in the lab's exact calibrated plate.
    """
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
        if "96" in n.lower() and ("deep" in n.lower() or "2ml" in n.lower() or "wellplate" in n.lower())
    )
    raise RuntimeError(
        "No known 96DW plate factory was found in this PyLabRobot install. "
        "Replace make_96dw_source_plate() with the lab-calibrated 96DW resource. "
        f"Possible nearby resource names: {available_96[:60]}"
    )


# -----------------------------
# Tuned p50 settings
# -----------------------------
P50_ASP_HEIGHT = [4.5] * 8
P50_ASP_OFFSETS = [Coordinate(0.20, 2.30, 0.5)] * 8

# Side-wall dispense style per validated low-volume WGS prep practices.
P50_WORK_DSP_HEIGHT = [8.0] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(DSP_X_RIGHT_SHIFT, 2.45, 27.0)] * 8


# -----------------------------
# Tuned p1000 settings
# -----------------------------
P1000_ASP_HEIGHT = [1.5] * 8
P1000_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P1000_MAG_DSP_HEIGHT = [8.0] * 8
P1000_MAG_DSP_OFFSETS = [Coordinate(DSP_X_RIGHT_SHIFT, 2.45, 27.0)] * 8


# -----------------------------
# Source 96DW layout
# Reagent columns are per-row A:H for 8-channel transfer.
# Bulk cleanup reagents use single 96DW wells repeated across 8 channels.
# Adjust this layout to match the physical 96DW map before wet run.
# -----------------------------
SRC_LYSIS_COL = 1
SRC_REACTION_COL = 2
SRC_DNAPREP_COL = 3
SRC_FERAT_COL = 4
SRC_ADAPTER_COL = 5
SRC_LP2L_COL = 6
SRC_LIBAMP_COL = 7

TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"


# -----------------------------
# Protocol volumes
# -----------------------------
VOL_LYSIS = 3
VOL_REACTION = 6
VOL_DNAPREP = 3
VOL_FERAT = 4
VOL_ADAPTER = 5
VOL_LP2L = 5
VOL_LIBAMP = 20

VOL_BEADS = 30
VOL_ETOH = 200
VOL_ELUTION = 42
VOL_FINAL_TRANSFER = 40


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


def mix_after_dispense(vol: float):
    # TEMP DISABLED 2026-04-27:
    # Mix caused geometry/Z issues during validation. Keep this helper so call sites
    # are easy to re-enable tomorrow, but return None for now.
    # Intended future behavior: reagent additions mix 3x; beads/elution mix 3x; ethanol no mix.
    return None


async def transfer_column(
    lh: LiquidHandler,
    source_wells,
    target_wells,
    vol: float,
    asp_height: List[float],
    asp_offsets: List[Coordinate],
    dsp_height: List[float],
    dsp_offsets: List[Coordinate],
    label: str,
):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL from {label}...")
    await lh.aspirate(
        source_wells,
        vols=volumes,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL into destination wells without mix...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )


async def transfer_from_trough(
    lh: LiquidHandler,
    source_well,
    target_wells,
    vol: float,
    asp_height: List[float],
    asp_offsets: List[Coordinate],
    dsp_height: List[float],
    dsp_offsets: List[Coordinate],
    label: str,
):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL x 8 from trough {label}...")
    await lh.aspirate(
        [source_well] * 8,
        vols=volumes,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print("Dispensing into rail 40 cleanup/magnet destination column without mix...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )


async def run_wga_additions(lh, p50_tips, source_96dw, work_plate):
    print("\n=== WGA ADDITIONS: rail 26 pos 1 96DW -> rail 33 pos 0 96WP ===")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_96dw[f"A{SRC_LYSIS_COL}:H{SRC_LYSIS_COL}"],
            wells_for_column(work_plate, col),
            VOL_LYSIS,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source 96DW column {SRC_LYSIS_COL} (Lysis Mix)",
        )

    print("PAUSE/TODO: seal, spin, mix 20 min RT at 1400 rpm, spin, plate on ice.")

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_96dw[f"A{SRC_REACTION_COL}:H{SRC_REACTION_COL}"],
            wells_for_column(work_plate, col),
            VOL_REACTION,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source 96DW column {SRC_REACTION_COL} (Reaction Mix)",
        )

    await lh.return_tips()
    print("PAUSE/TODO: seal, spin, mix 1 min RT at 1000 rpm, spin, thermocycler DNA Amplification.")


async def run_library_prep_additions(lh, p50_tips, source_96dw, work_plate):
    print("\n=== LIBRARY PREP ADDITIONS: rail 26 pos 1 96DW -> rail 33 pos 0 96WP ===")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_96dw[f"A{SRC_DNAPREP_COL}:H{SRC_DNAPREP_COL}"],
            wells_for_column(work_plate, col),
            VOL_DNAPREP,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source 96DW column {SRC_DNAPREP_COL} (DNA Prep Master Mix)",
        )

    print("PAUSE/TODO: seal, spin/vortex/spin, DNAPREP thermocycler program.")

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_96dw[f"A{SRC_FERAT_COL}:H{SRC_FERAT_COL}"],
            wells_for_column(work_plate, col),
            VOL_FERAT,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source 96DW column {SRC_FERAT_COL} (FERAT Master Mix)",
        )

    print("PAUSE/TODO: seal, vortex/spin, FERAT thermocycler program.")

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_96dw[f"A{SRC_ADAPTER_COL}:H{SRC_ADAPTER_COL}"],
            wells_for_column(work_plate, col),
            VOL_ADAPTER,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source 96DW column {SRC_ADAPTER_COL} (UDI Adapters - VERIFY MAP)",
        )

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_96dw[f"A{SRC_LP2L_COL}:H{SRC_LP2L_COL}"],
            wells_for_column(work_plate, col),
            VOL_LP2L,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source 96DW column {SRC_LP2L_COL} (LP2L)",
        )

    print("PAUSE/TODO: seal/mix/spin, 20C ligation 15 min.")

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_96dw[f"A{SRC_LIBAMP_COL}:H{SRC_LIBAMP_COL}"],
            wells_for_column(work_plate, col),
            VOL_LIBAMP,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source 96DW column {SRC_LIBAMP_COL} (Amplification Master Mix)",
        )

    await lh.return_tips()
    print("PAUSE/TODO: seal/mix/spin, LIB-AMP thermocycler program.")


async def run_cleanup_additions_on_magnet(lh, p1000_tips, trough, mag_plate):
    print("\n=== POST-AMPLIFICATION CLEANUP ADDITIONS: reservoir/trough -> rail 40 pos 0 ===")
    print("NOTE: iSWAP is not implemented yet. Before this phase, the reaction plate must be at rail 40 pos 0.")

    await lh.pick_up_tips(p1000_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_BEADS][0],
            wells_for_column(mag_plate, col),
            VOL_BEADS,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_BEADS} (SPRI cleanup beads)",
        )

    print("PAUSE/TODO: seal/vortex high 10 sec, incubate RT 5 min, spin 10 sec, magnet 3 min/until clear.")
    print("TODO: remove supernatant on magnet to waste with bead-safe aspiration geometry.")

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_ETOH1][0],
            wells_for_column(mag_plate, col),
            VOL_ETOH,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_ETOH1} (80% EtOH wash 1)",
        )

    print("PAUSE/TODO: incubate on magnet 30 sec.")
    print("TODO: remove ethanol wash 1 to waste with bead-safe aspiration geometry.")

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_ETOH2][0],
            wells_for_column(mag_plate, col),
            VOL_ETOH,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_ETOH2} (80% EtOH wash 2)",
        )

    print("PAUSE/TODO: incubate on magnet 30 sec.")
    print("TODO: remove ethanol wash 2, spin, return to magnet, residual ethanol removal, dry 3 min.")

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_ELUTION][0],
            wells_for_column(mag_plate, col),
            VOL_ELUTION,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_ELUTION} (Elution Buffer)",
        )

    print("PAUSE/TODO: off magnet resuspend/mix, incubate RT 2 min, spin, magnet 2 min/until clear.")
    print("TODO: transfer 40 uL eluate to final output plate after output deck position is finalized.")

    await lh.return_tips()


async def main():
    print("Initializing STAR with skip_autoload=True...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

    try:
        print("Assigning deck resources...")

        tip_carrier = TIP_CAR_480_A00(name=f"tip_car_rail{TIP_RAIL}")
        lh.deck.assign_child_resource(tip_carrier, rails=TIP_RAIL)

        source_carrier = PLT_CAR_L5AC_A00(name=f"source_car_rail{SOURCE_RAIL}")
        lh.deck.assign_child_resource(source_carrier, rails=SOURCE_RAIL)

        work_carrier = PLT_CAR_L5AC_A00(name=f"work_car_rail{WORK_RAIL}")
        lh.deck.assign_child_resource(work_carrier, rails=WORK_RAIL)

        mag_carrier = PLT_CAR_L5AC_A00(name=f"mag_car_rail{MAG_RAIL}")
        lh.deck.assign_child_resource(mag_carrier, rails=MAG_RAIL)

        p1000_tips = hamilton_96_tiprack_1000uL_filter(name="p1000_filter_tips")
        p50_tips = hamilton_96_tiprack_50uL_filter(name="p50_filter_tips")

        source_96dw = make_96dw_source_plate(name="source_reagent_96dw")
        trough = CellTreat_12_troughplate_15000ul_Vb(name="bulk_liquid_trough")
        work_plate = CellTreat_96_wellplate_350ul_Fb(name="work_96wp")
        mag_plate = CellTreat_96_wellplate_350ul_Fb(name="mag_cleanup_96wp")

        tip_carrier[P1000_TIP_POS] = p1000_tips
        tip_carrier[P50_TIP_POS] = p50_tips

        source_carrier[SOURCE_POS] = source_96dw
        source_carrier[TROUGH_POS] = trough
        work_carrier[WORK_POS] = work_plate
        mag_carrier[MAG_POS] = mag_plate

        await run_wga_additions(lh, p50_tips, source_96dw, work_plate)
        await run_library_prep_additions(lh, p50_tips, source_96dw, work_plate)

        print("\n=== iSWAP STUBS TO ADD AFTER LH VALIDATION ===")
        print("TODO iSWAP: move work_96wp rail 33 pos 0 -> thermocycler/thermal modules as needed.")
        print("TODO iSWAP: move amplified library plate -> rail 40 pos 0 for cleanup.")
        print("For now, cleanup LH assumes the reaction plate is already present at rail 40 pos 0.")

        await run_cleanup_additions_on_magnet(lh, p1000_tips, trough, mag_plate)

    finally:
        print("Stopping LiquidHandler...")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
