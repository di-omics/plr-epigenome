from pathlib import Path as _MethodPath
import sys as _method_sys

_METHOD_ROOT = next(
    parent for parent in _MethodPath(__file__).resolve().parents
    if parent.name == "hamilton-star"
)
if str(_METHOD_ROOT) not in _method_sys.path:
    _method_sys.path.insert(0, str(_METHOD_ROOT))
from operator_parameters import required_nonnegative, required_positive

import asyncio

from pylabrobot.liquid_handling import LiquidHandler
from pylabrobot.liquid_handling.backends import STARBackend
from pylabrobot.resources.hamilton import STARDeck, TIP_CAR_480_A00
from pylabrobot.resources import (
    PLT_CAR_L5AC_A00,
    CellTreat_12_troughplate_15000ul_Vb,
    CellTreat_96_wellplate_350ul_Fb,
    CellTreat_96_wellplate_350ul_Ub,
    hamilton_96_tiprack_1000uL_filter,
    hamilton_96_tiprack_50uL_filter,
    Coordinate,
)

# ---------------------------------------------------------------------
# WGS preparation (WGS preparation) - liquid handling first pass
#
# Assumptions for this scaffold:
# - Working/sample plate is at rail 33 pos 0.
# - Magnetic cleanup plate position is rail 40 pos 0.
# - For now, rail 40 pos 0 reuses the same p1000 destination settings
#   as rail 33 pos 0 until magnet-position-specific tuning is done.
# - iSWAP / ODTC moves are NOT implemented yet. This file only covers
#   liquid movements.
# - Start with 8 samples in column 1. Scaling to additional columns is
#   done by extending DEST_COLUMNS.
# - Adapter addition is left as a TODO because each well needs a unique
#   adapter assignment.
# ---------------------------------------------------------------------

TIP_RAIL = 19
P1000_TIP_POS = 0
P50_TIP_POS = 1

SOURCE_RAIL = 26
SOURCE_POS = 1
TROUGH_POS = 2

WORK_RAIL = 33
WORK_POS = 0

MAG_RAIL = 40
MAG_POS = 0

DEST_COLUMNS = [1]   # v1: 8 samples only; extend later to [1,2,...]

# -----------------------------
# Tuned p50 settings
# -----------------------------
P50_ASP_HEIGHT = [4.5] * 8
P50_ASP_OFFSETS = [Coordinate(0.20, 2.30, 0.5)] * 8

P50_WORK_DSP_HEIGHT = [5.0] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(0.10, 2.45, 27.0)] * 8

# -----------------------------
# Tuned p1000 settings
# -----------------------------
P1000_ASP_HEIGHT = [1.5] * 8
P1000_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P1000_WORK_DSP_HEIGHT = [5.0] * 8
P1000_WORK_DSP_OFFSETS = [Coordinate(0.10, 2.20, 30.0)] * 8

# Placeholder: use same destination behavior for rail 40 pos 0 cleanup
P1000_MAG_DSP_HEIGHT = P1000_WORK_DSP_HEIGHT
P1000_MAG_DSP_OFFSETS = P1000_WORK_DSP_OFFSETS

# -----------------------------
# Source layout
# 96-well source plate columns
# -----------------------------
SRC_LYSIS_COL = 1
SRC_REACTION_COL = 2
SRC_DNA_FRAGMENTATION_COL = 3
SRC_END_REPAIR_COL = 4
SRC_LIGATION_MIX_COL = 5
SRC_LIBRARY_PCR_COL = 6
# SRC_ADAPTERS: TODO, unique-per-well logic later

# -----------------------------
# Trough layout
# -----------------------------
TROUGH_BEADS = "A1"
TROUGH_ETOH1 = "A2"
TROUGH_ETOH2 = "A3"
TROUGH_ELUTION = "A4"

# -----------------------------
# Configured workflow volumes
# -----------------------------
VOL_LYSIS = required_positive("wgs.stage_1_volume_ul")
VOL_REACTION = required_positive("wgs.stage_2_volume_ul")
VOL_DNA_FRAGMENTATION = required_positive("wgs.stage_3_volume_ul")
VOL_END_REPAIR = required_positive("wgs.stage_4_volume_ul")
VOL_ADAPTER = required_positive("wgs.stage_5_volume_ul")
VOL_LIGATION_MIX = required_positive("wgs.stage_6_volume_ul")
VOL_LIBRARY_PCR = required_positive("wgs.stage_7_volume_ul")

VOL_BEADS = required_positive("wgs.cleanup.bead_volume_ul")
VOL_ETOH = required_positive("wgs.cleanup.wash_add_ul")
VOL_ELUTION = required_positive("wgs.cleanup.elution_ul")
VOL_FINAL_TRANSFER = required_positive("wgs.cleanup.final_transfer_ul")


async def transfer_column(
    lh,
    source_wells,
    target_wells,
    vol,
    asp_height,
    asp_offsets,
    dsp_height,
    dsp_offsets,
    label,
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

    print(f"Dispensing {vol} uL into destination wells...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )


async def transfer_from_trough(
    lh,
    source_well,
    target_wells,
    vol,
    asp_height,
    asp_offsets,
    dsp_height,
    dsp_offsets,
    label,
):
    volumes = [vol] * 8

    print(f"Aspirating {vol} uL from trough {label}...")
    await lh.aspirate(
        [source_well] * 8,
        vols=volumes,
        liquid_height=asp_height,
        offsets=asp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )

    print(f"Dispensing {vol} uL into destination wells...")
    await lh.dispense(
        target_wells,
        vols=volumes,
        liquid_height=dsp_height,
        offsets=dsp_offsets,
        blow_out_air_volume=[0.0] * 8,
    )


def wells_for_column(plate, col: int):
    return plate[f"A{col}:H{col}"]


async def run_wgs_prep_additions(lh, p50_tips, source_plate, work_plate):
    print("\n=== WGS PREPARATION ADDITIONS ===")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_LYSIS_COL}:H{SRC_LYSIS_COL}"],
            wells_for_column(work_plate, col),
            VOL_LYSIS,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source plate column {SRC_LYSIS_COL} (Lysis Mix)",
        )

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_REACTION_COL}:H{SRC_REACTION_COL}"],
            wells_for_column(work_plate, col),
            VOL_REACTION,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source plate column {SRC_REACTION_COL} (Reaction Mix)",
        )

    await lh.return_tips()

    print("TODO after WGS preparation additions: seal / spin / mix / thermocycler per protocol.")


async def run_library_prep_additions(lh, p50_tips, source_plate, work_plate):
    print("\n=== LIBRARY PREP ADDITIONS ===")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_DNA_FRAGMENTATION_COL}:H{SRC_DNA_FRAGMENTATION_COL}"],
            wells_for_column(work_plate, col),
            VOL_DNA_FRAGMENTATION,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source plate column {SRC_DNA_FRAGMENTATION_COL} (DNA fragmentation mix)",
        )

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_END_REPAIR_COL}:H{SRC_END_REPAIR_COL}"],
            wells_for_column(work_plate, col),
            VOL_END_REPAIR,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source plate column {SRC_END_REPAIR_COL} (end-repair mix)",
        )

    # TODO unique adapter mapping
    print("TODO: adapter addition not automated in v1 scaffold (unique UDI per well).")

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_LIGATION_MIX_COL}:H{SRC_LIGATION_MIX_COL}"],
            wells_for_column(work_plate, col),
            VOL_LIGATION_MIX,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source plate column {SRC_LIGATION_MIX_COL} (ligation master mix)",
        )

    for col in DEST_COLUMNS:
        await transfer_column(
            lh,
            source_plate[f"A{SRC_LIBRARY_PCR_COL}:H{SRC_LIBRARY_PCR_COL}"],
            wells_for_column(work_plate, col),
            VOL_LIBRARY_PCR,
            P50_ASP_HEIGHT,
            P50_ASP_OFFSETS,
            P50_WORK_DSP_HEIGHT,
            P50_WORK_DSP_OFFSETS,
            f"source plate column {SRC_LIBRARY_PCR_COL} (library PCR mix)",
        )

    await lh.return_tips()

    print("TODO after library-prep additions: seal / vortex / spin / thermocycler per protocol.")


async def run_cleanup_on_magnet(lh, p1000_tips, trough, mag_plate, output_plate):
    print("\n=== CLEANUP AT MAGNET POSITION (rail 40 pos 0) ===")
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

    print("TODO after beads: seal / vortex / incubate / magnet clear.")

    print("TODO: remove supernatant on magnet.")

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

    print("TODO: remove ethanol wash 1 on magnet.")

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

    print("TODO: remove ethanol wash 2 on magnet.")
    print("TODO: remove residual ethanol / air dry.")

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

    print("TODO after elution: incubate / magnet clear.")

    print("TODO: transfer the operator-approved final eluate volume from the magnet plate to the output plate.")
    # Placeholder only; real supernatant removal settings need separate tuning.

    await lh.return_tips()


async def main():
    print("Initializing STAR...")
    lh = LiquidHandler(backend=STARBackend(), deck=STARDeck())
    await lh.setup(skip_autoload=True)

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

    source_plate = CellTreat_96_wellplate_350ul_Ub(name="source_reagent_plate")
    trough = CellTreat_12_troughplate_15000ul_Vb(name="bulk_liquid_trough")

    work_plate = CellTreat_96_wellplate_350ul_Fb(name="work_plate")
    mag_plate = CellTreat_96_wellplate_350ul_Fb(name="mag_cleanup_plate")
    output_plate = CellTreat_96_wellplate_350ul_Fb(name="cleanup_output_plate")

    tip_carrier[P1000_TIP_POS] = p1000_tips
    tip_carrier[P50_TIP_POS] = p50_tips

    source_carrier[SOURCE_POS] = source_plate
    source_carrier[TROUGH_POS] = trough

    work_carrier[WORK_POS] = work_plate
    mag_carrier[MAG_POS] = mag_plate

    # output_plate is not placed yet in this first-pass scaffold;
    # final placement can be decided once iSWAP / deck layout is finalized.

    await run_wgs_prep_additions(lh, p50_tips, source_plate, work_plate)
    await run_library_prep_additions(lh, p50_tips, source_plate, work_plate)

    print("TODO: iSWAP move work_plate -> mag_plate before cleanup.")
    await run_cleanup_on_magnet(lh, p1000_tips, trough, mag_plate, output_plate)

    print("Stopping...")
    await lh.stop()
    print("Done.")


asyncio.run(main())
