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
# whole-genome sequencing - Hamilton STAR / PyLabRobot
# LH + verified iSWAP movement scaffold.
#
# Deck intent from Di:
# - Reagent/source liquid starts on rail 26, carrier position 1, 96DW.
# - Beads/ethanol/elution are in reservoir/trough on rail 26, carrier position 2.
# - Working 96-well plate is on rail 33, carrier position 0, 96WP.
# - All bead/ethanol cleanup liquid handling happens on rail 40, position 0.
# - iSWAP 33 -> 40 -> 33 is integrated using the verified XY/Z offsets.
# - 96WP dispense X offsets are shifted slightly right to avoid grabbing/lifting the plate.
# - Mix enabled using working Mix(...) pattern; ethanol washes are dispense-only.
#
# Safety:
# - Uses lh.setup(skip_autoload=True).
# - Keep the deck clear before init/homing.
# - This script implements the verified iSWAP 33 -> 40 -> 33 movement.
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

DEST_COLUMNS = [1, 2, 3, 4]  # v1: A1:H1 only. Extend to [1, 2, ...] after validation.

# Dispense/mix tuning.
# Positive X moves the dispense position slightly right in the 96WP.
# Increase/decrease by small increments after dry/water validation.
DSP_X_RIGHT_SHIFT = 0.35
MIX_REPETITIONS = 3
MIX_FLOW_RATE = 100
DISPENSE_BLOWOUT_AIR_VOLUME = 5.0  # uL; dispense-only blowout test

# VERIFIED iSWAP offsets from working 33 -> 40 -> 33 test.
# Apply same offset to iSWAP pickup/dropoff target locations.
ISWAP_OFFSET_X_MM = 0.0
ISWAP_OFFSET_Y_MM = 3.5
ISWAP_OFFSET_Z_MM = 40.0



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
P50_ASP_HEIGHT = [2.0] * 8
P50_ASP_OFFSETS = [Coordinate(0.20, 2.30, 0.0)] * 8

# Side-wall dispense style per the vendor best practices.
P50_WORK_DSP_HEIGHT = [10.0] * 8
P50_WORK_DSP_OFFSETS = [Coordinate(DSP_X_RIGHT_SHIFT, 2.45, 24.0)] * 8


# -----------------------------
# Tuned p1000 settings
# -----------------------------
P1000_ASP_HEIGHT = [1.5] * 8
P1000_ASP_OFFSETS = [Coordinate(0.0, 1.5, 0.0)] * 8

P1000_MAG_DSP_HEIGHT = [13.0] * 8
P1000_MAG_DSP_OFFSETS = [Coordinate(-0.60, 1.55, 27.0)] * 8


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


def offset_location(resource, dx=0.0, dy=0.0, dz=0.0):
    loc = resource.location
    if loc is None:
        raise RuntimeError(
            f"{resource.name} has no location. "
            "This usually means it was not assigned to a carrier/site yet."
        )

    resource.location = Coordinate(
        loc.x + dx,
        loc.y + dy,
        loc.z + dz,
    )


def apply_verified_iswap_offset(resource):
    offset_location(
        resource,
        ISWAP_OFFSET_X_MM,
        ISWAP_OFFSET_Y_MM,
        ISWAP_OFFSET_Z_MM,
    )


def mix_after_dispense(vol: float):
    # Working Mix(...) pattern from serial dilution test.
    # Conservative volume for small whole-genome sequencing reagent additions.
    mix_vol = max(1.0, min(float(vol), 20.0))
    return [Mix(volume=mix_vol, repetitions=MIX_REPETITIONS, flow_rate=MIX_FLOW_RATE)] * 8


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
    do_mix: bool = True,
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

    if do_mix:
        print(f"Dispensing {vol} uL into destination wells with 3x mix...")
        await lh.dispense(
            target_wells,
            vols=volumes,
            liquid_height=dsp_height,
            offsets=dsp_offsets,
            blow_out_air_volume=[DISPENSE_BLOWOUT_AIR_VOLUME] * 8,
            mix=mix_after_dispense(vol),
        )
    else:
        print(f"Dispensing {vol} uL into destination wells without mix...")
        await lh.dispense(
            target_wells,
            vols=volumes,
            liquid_height=dsp_height,
            offsets=dsp_offsets,
            blow_out_air_volume=[DISPENSE_BLOWOUT_AIR_VOLUME] * 8,
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
    do_mix: bool = True,
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

    if do_mix:
        print("Dispensing into rail 40 cleanup/magnet destination column with 3x mix...")
        await lh.dispense(
            target_wells,
            vols=volumes,
            liquid_height=dsp_height,
            offsets=dsp_offsets,
            blow_out_air_volume=[DISPENSE_BLOWOUT_AIR_VOLUME] * 8,
            mix=mix_after_dispense(vol),
        )
    else:
        print("Dispensing into rail 40 cleanup/magnet destination column without mix...")
        await lh.dispense(
            target_wells,
            vols=volumes,
            liquid_height=dsp_height,
            offsets=dsp_offsets,
            blow_out_air_volume=[DISPENSE_BLOWOUT_AIR_VOLUME] * 8,
        )


async def run_phase_1_pta_wga_additions(lh, p50_tips, source_96dw, work_plate):
    print("\n=== PHASE 1: PTA/WGA SETUP: rail 26 pos 1 96DW -> rail 33 pos 0 96WP ===")
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
            do_mix=True,
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
            do_mix=True,
        )

    await lh.return_tips()
    print("PAUSE/TODO: seal, spin, mix 1 min RT at 1000 rpm, spin, thermocycler DNA Amplification.")


async def run_phase_2_to_4_library_prep_additions(lh, p50_tips, source_96dw, work_plate):
    print("\n=== PHASE 2-4: LIBRARY PREP ADDITIONS: rail 26 pos 1 96DW -> rail 33 pos 0 96WP ===")
    await lh.pick_up_tips(p50_tips["A1:H1"])

    print("\n--- PHASE 2: DNA PREP MASTER MIX ADDITION ---")
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
        do_mix=True,
        )

    print("PAUSE/TODO: seal, spin/vortex/spin, DNAPREP thermocycler program: 37C 10 min, 4C hold.")

    print("\n--- PHASE 3: FERAT MASTER MIX ADDITION ---")
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
        do_mix=True,
        )

    print("PAUSE/TODO: seal, vortex/spin, FERAT thermocycler program: 4C 30 sec, 30C 5 min, 65C 30 min, 4C hold.")

    print("\n--- PHASE 4A: LIGATION ADDITIONS: ADAPTERS + LP2L ---")
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
        do_mix=True,
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
        do_mix=True,
        )

    print("PAUSE/TODO: seal/mix/spin, 20C ligation 15 min.")

    print("\n--- PHASE 4B: LIBRARY AMPLIFICATION MASTER MIX ADDITION ---")
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
        do_mix=True,
        )

    await lh.return_tips()
    print("PAUSE/TODO: seal/mix/spin, LIB-AMP thermocycler program.")


async def run_post_amp_cleanup_additions_on_magnet(lh, p1000_tips, trough, cleanup_plate):
    print("\n=== PHASE 5: POST-LIB-AMP BEAD CLEANUP ADDITIONS: reservoir/trough -> rail 40 pos 0 ===")
    print("NOTE: iSWAP already moved the reaction plate to rail 40 pos 0 before this cleanup phase.")

    await lh.pick_up_tips(p1000_tips["A1:H1"])

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_BEADS][0],
            wells_for_column(cleanup_plate, col),
            VOL_BEADS,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_BEADS} (Resolve Beads)",
        do_mix=False,
        )

    print("PAUSE/TODO: seal/vortex high 10 sec, incubate RT 5 min, spin 10 sec, magnet 3 min/until clear.")
    print("TODO: remove supernatant on magnet to waste with bead-safe aspiration geometry.")

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_ETOH1][0],
            wells_for_column(cleanup_plate, col),
            VOL_ETOH,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_ETOH1} (80% EtOH wash 1)",
        do_mix=False,
        )

    print("PAUSE/TODO: incubate on magnet 30 sec.")
    print("TODO: remove ethanol wash 1 to waste with bead-safe aspiration geometry.")

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_ETOH2][0],
            wells_for_column(cleanup_plate, col),
            VOL_ETOH,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_ETOH2} (80% EtOH wash 2)",
        do_mix=False,
        )

    print("PAUSE/TODO: incubate on magnet 30 sec.")
    print("TODO: remove ethanol wash 2, spin, return to magnet, residual ethanol removal, dry 3 min.")

    for col in DEST_COLUMNS:
        await transfer_from_trough(
            lh,
            trough[TROUGH_ELUTION][0],
            wells_for_column(cleanup_plate, col),
            VOL_ELUTION,
            P1000_ASP_HEIGHT,
            P1000_ASP_OFFSETS,
            P1000_MAG_DSP_HEIGHT,
            P1000_MAG_DSP_OFFSETS,
            f"{TROUGH_ELUTION} (Elution Buffer)",
        do_mix=False,
        )

    print("PAUSE/TODO: off magnet resuspend/mix, incubate RT 2 min, spin, magnet 2 min/until clear.")
    print("TODO: transfer 40 uL eluate to final output plate after output deck position is finalized.")

    await lh.return_tips()


async def move_work_plate_33_to_40(lh, work_plate, cleanup_carrier):
    """Move actual work plate from rail 33 pos 0 to empty rail 40 pos 0.

    Important: the verified iSWAP offset is only for the iSWAP pickup/dropoff move.
    After the move, restore the rail 40 carrier site location so downstream liquid
    handling uses the normal rail 40 coordinates.
    """
    print("\n=== iSWAP MOVE: rail 33 pos 0 -> rail 40 pos 0 ===")
    print(f"Using iSWAP offset X={ISWAP_OFFSET_X_MM}, Y={ISWAP_OFFSET_Y_MM}, Z={ISWAP_OFFSET_Z_MM} mm")

    print("Preparing pickup from rail 33 pos 0...")
    print(f"Original plate location: {work_plate.location}")
    apply_verified_iswap_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")

    cleanup_site = cleanup_carrier[MAG_POS]
    cleanup_site_original_location = Coordinate(
        cleanup_site.location.x,
        cleanup_site.location.y,
        cleanup_site.location.z,
    )

    print("Preparing dropoff to rail 40 pos 0...")
    print(f"Original cleanup site location: {cleanup_site.location}")
    apply_verified_iswap_offset(cleanup_site)
    print(f"Offset cleanup dropoff location: {cleanup_site.location}")

    print("Step: moving rail 33 pos 0 -> rail 40 pos 0...")
    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, cleanup_site)

    # Restore the rail 40 site location before any cleanup liquid handling.
    cleanup_site.location = cleanup_site_original_location
    print(f"Restored rail 40 cleanup site location for LH: {cleanup_site.location}")
    print("iSWAP move to rail 40 complete.")


async def move_work_plate_40_to_33(lh, work_plate, work_carrier):
    """Move actual work plate from rail 40 pos 0 back to empty rail 33 pos 0.

    The verified offset is again used only for the iSWAP pickup/dropoff move.
    Restore the rail 33 site location after the move for a clean deck model.
    """
    print("\n=== iSWAP MOVE: rail 40 pos 0 -> rail 33 pos 0 ===")
    print(f"Current plate pickup location before offset: {work_plate.location}")

    print("Preparing pickup from rail 40 pos 0...")
    apply_verified_iswap_offset(work_plate)
    print(f"Offset plate pickup location: {work_plate.location}")

    return_site = work_carrier[WORK_POS]
    return_site_original_location = Coordinate(
        return_site.location.x,
        return_site.location.y,
        return_site.location.z,
    )

    print("Preparing dropoff back to rail 33 pos 0...")
    print(f"Original return site location: {return_site.location}")
    apply_verified_iswap_offset(return_site)
    print(f"Offset return dropoff location: {return_site.location}")

    print("Step: moving rail 40 pos 0 -> rail 33 pos 0...")
    async with lh.backend.slow_iswap():
        await lh.move_plate(work_plate, return_site)

    # Restore rail 33 site location after movement.
    return_site.location = return_site_original_location
    print(f"Restored rail 33 return site location: {return_site.location}")
    print("iSWAP return to rail 33 complete.")


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

        tip_carrier[P1000_TIP_POS] = p1000_tips
        tip_carrier[P50_TIP_POS] = p50_tips

        source_carrier[SOURCE_POS] = source_96dw
        source_carrier[TROUGH_POS] = trough
        work_carrier[WORK_POS] = work_plate

        await run_phase_1_pta_wga_additions(lh, p50_tips, source_96dw, work_plate)
        await run_phase_2_to_4_library_prep_additions(lh, p50_tips, source_96dw, work_plate)

        # Move the actual work plate to rail 40 for post-LIB-AMP cleanup.
        await move_work_plate_33_to_40(lh, work_plate, mag_carrier)

        # Cleanup targets the same moved work_plate object, now physically at rail 40.
        await run_post_amp_cleanup_additions_on_magnet(lh, p1000_tips, trough, work_plate)

        # Return the same plate to rail 33 after cleanup additions.
        await move_work_plate_40_to_33(lh, work_plate, work_carrier)

    finally:
        print("Parking / stopping...")
        try:
            await lh.backend.park_iswap()
        except Exception as e:
            print(f"park_iswap warning: {e!r}")
        await lh.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
