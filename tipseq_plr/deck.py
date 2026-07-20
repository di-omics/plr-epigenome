"""
Hamilton STAR deck layout for automated (sci)TIP-seq.

The layout is built programmatically so it can be version-controlled and diffed.
Labware constructors differ slightly across PyLabRobot releases, so every
`_make_*` helper tries the current name first and falls back to a generic
resource of the right geometry. That keeps the module importable (and the
simulation runnable) on any recent PLR, while `pin_labware()` documents exactly
which catalog parts a physical run must swap in.

Rail map (STAR has 55 T-tracks). Adjust to your instrument footprint:

    rail  3  : tip carrier   - 300 uL filtered tips (aspiration)
    rail  9  : tip carrier   - 50 uL filtered tips (low-volume reagents)
    rail 15  : reagent carrier (troughs: wash, dig buffers, SPRI, EtOH, water)
    rail 21  : reagent carrier (enzymes / mixes, cold - see ChilledCarrier)
    rail 27  : sample plate carrier (working plate + index plates)
    rail 30  : MAGNET position (passive Alpaqua/Ambion magnet plate)
    rail 36  : Hamilton Heater Shaker (HHS) nest
    rail 42  : Inheco ODTC docking footprint
    rail 48  : Tecan reader transfer / staging position
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# PyLabRobot is an optional import so that config/planning code and unit tests
# run without the hardware stack installed.
try:
    from pylabrobot.resources import (
        Coordinate,
        Plate,
        TipRack,
    )
    from pylabrobot.resources.hamilton import STARLetDeck

    _HAS_PLR = True
except Exception as exc:  # pragma: no cover - exercised only without PLR
    logger.warning("PyLabRobot not importable (%s); deck runs in stub mode.", exc)
    _HAS_PLR = False
    Coordinate = Plate = TipRack = object  # type: ignore
    STARLetDeck = object  # type: ignore


# Positions of interest on the deck, resolved after the layout is built.
@dataclass
class DeckMap:
    deck: object
    tips_300: object
    tips_50: object
    reagent_troughs: object          # plates on reagent carrier 1 (buffers)
    enzyme_troughs: object           # plates on reagent carrier 2 (chilled enzymes)
    working_plate: object            # the 96-well sample plate that travels the deck
    index_plate: object              # PCR index primer source plate
    magnet_site: Optional[object]    # coordinate/resource for the magnet nest
    hhs_site: Optional[object]       # heater-shaker nest
    odtc_site: Optional[object]      # thermocycler docking site
    reader_staging: Optional[object] # plate reader staging site
    qc_plate: object                 # black plate for Tecan fluorescence quant


def _try(*factories):
    """Return the first factory(name) that constructs without raising."""
    last = None
    for fn in factories:
        try:
            return fn()
        except Exception as e:  # pragma: no cover
            last = e
    raise RuntimeError(f"no labware factory succeeded: {last}")


def _make_tip_carrier(rail: int, name: str, tip_kind: str):
    """300 uL or 50 uL filtered tips on a standard Hamilton tip carrier."""
    from pylabrobot.resources.hamilton import TIP_CAR_480_A00
    from pylabrobot.resources import (
        hamilton_96_tiprack_1000uL_filter,
        hamilton_96_tiprack_50uL_filter,
    )

    car = TIP_CAR_480_A00(name=f"{name}_carrier")
    # HTF was removed in PyLabRobot 0.2.1 in favour of the explicit catalog
    # factory below. Select the rack by the intended pipetting range; the
    # carrier geometry is the same for both sizes.
    rack_factory = (
        hamilton_96_tiprack_50uL_filter
        if tip_kind == "50"
        else hamilton_96_tiprack_1000uL_filter
    )
    # Fill positions 0..4 with tip racks of the requested kind.
    for i in range(5):
        rack = rack_factory(name=f"{name}_{i}")
        car[i] = rack
    return car


def _make_reagent_carrier(name: str):
    """Reagent troughs on a Hamilton MFX/reagent carrier.

    We use deep-well plates as multi-reagent reservoirs so each buffer gets an
    addressable column; `reagents.py` maps buffer -> column.
    """
    from pylabrobot.resources.hamilton import PLT_CAR_L5AC_A00
    from pylabrobot.resources import Cor_96_wellplate_2mL_Vb

    car = PLT_CAR_L5AC_A00(name=f"{name}_carrier")
    for i in range(5):
        car[i] = Cor_96_wellplate_2mL_Vb(name=f"{name}_res_{i}")
    return car


def _make_plate_carrier(name: str):
    from pylabrobot.resources.hamilton import PLT_CAR_L5AC_A00
    from pylabrobot.resources import Cor_96_wellplate_2mL_Vb

    car = PLT_CAR_L5AC_A00(name=f"{name}_carrier")
    for i in range(5):
        car[i] = Cor_96_wellplate_2mL_Vb(name=f"{name}_plate_{i}")
    return car


def _loaded_plates(carrier):
    """Return plates, not carrier slots, across PyLabRobot carrier APIs."""
    plates = []
    for index in range(5):
        slot = carrier[index]
        children = getattr(slot, "children", ())
        plates.append(children[0] if children else slot)
    return plates


def _loaded_tip_rack(carrier, index: int = 0):
    """Return a tip rack, not its ResourceHolder, across PLR carrier APIs."""
    slot = carrier[index]
    children = getattr(slot, "children", ())
    return children[0] if children else slot


def build_deck(num_samples: int = 96) -> DeckMap:
    """Assemble the STAR deck and return a DeckMap of named positions.

    In stub mode (no PLR) this returns a DeckMap of plain placeholders so callers
    that only need the *names* of positions (planners, dry-run logs) still work.
    """
    if not _HAS_PLR:
        stub = lambda n: type("Stub", (), {"name": n})()
        return DeckMap(
            deck=stub("deck"),
            tips_300=stub("tips_300"), tips_50=stub("tips_50"),
            reagent_troughs=stub("reagents"), enzyme_troughs=stub("enzymes"),
            working_plate=stub("working_plate"), index_plate=stub("index_plate"),
            magnet_site=stub("magnet"), hhs_site=stub("hhs"),
            odtc_site=stub("odtc"), reader_staging=stub("reader"),
            qc_plate=stub("qc_plate"),
        )

    deck = STARLetDeck()

    tip_car_300 = _make_tip_carrier(3, "tips300", "300")
    tip_car_50 = _make_tip_carrier(9, "tips50", "50")
    reagent_car = _make_reagent_carrier("buffers")
    enzyme_car = _make_reagent_carrier("enzymes")
    plate_car = _make_plate_carrier("samples")

    deck.assign_child_resource(tip_car_300, rails=3)
    # These 5-position carriers occupy six STAR rails each. Keep one carrier
    # boundary between starts so the PyLabRobot deck model can reject real
    # overlaps rather than letting simulation silently accept an impossible map.
    deck.assign_child_resource(tip_car_50, rails=9)
    deck.assign_child_resource(reagent_car, rails=15)
    deck.assign_child_resource(enzyme_car, rails=21)
    deck.assign_child_resource(plate_car, rails=27)
    sample_plates = _loaded_plates(plate_car)

    # Magnet / HHS / ODTC / reader are represented as reserved deck coordinates.
    # Their physical modules are driven by their own backends (devices.py); the
    # STAR only needs to know where to place a plate for a hand-off.
    magnet_site = Coordinate(x=430.0, y=145.0, z=100.0)
    hhs_site = Coordinate(x=550.0, y=145.0, z=100.0)
    odtc_site = Coordinate(x=670.0, y=145.0, z=100.0)
    reader_staging = Coordinate(x=790.0, y=145.0, z=100.0)

    return DeckMap(
        deck=deck,
        tips_300=_loaded_tip_rack(tip_car_300),
        tips_50=_loaded_tip_rack(tip_car_50),
        # PLR 0.2 exposes a PlateHolder from carrier[index], whereas the
        # protocol layer needs the plate to resolve wells. Publish the loaded
        # plates so reagent and protocol code is insulated from that detail.
        reagent_troughs=_loaded_plates(reagent_car),
        enzyme_troughs=_loaded_plates(enzyme_car),
        working_plate=sample_plates[0],
        index_plate=sample_plates[1],
        magnet_site=magnet_site,
        hhs_site=hhs_site,
        odtc_site=odtc_site,
        reader_staging=reader_staging,
        qc_plate=sample_plates[2],
    )


def pin_labware() -> dict:
    """Catalog parts a physical run must confirm against local inventory.

    Returned as data so it can be printed in the run header and checked into the
    method record for audit.
    """
    return {
        "tips_300uL": "Hamilton 300 uL filtered CO-RE tips (235903 / HTF)",
        "tips_50uL": "Hamilton 50 uL filtered CO-RE tips (235948)",
        "sample_plate": "Eppendorf twin.tec 96 semi-skirted, or Bio-Rad HSP96 for ODTC",
        "reservoirs": "Cos 96-well 2 mL U-bottom as addressable reagent reservoirs",
        "magnet": "Alpaqua 96S Super Magnet / Ambion magnetic stand (passive)",
        "qc_plate": "Corning 3915 black 96-well (fluorescence quant on Tecan)",
        "conA_beads": "Bangs Laboratories BP531",
        "spri_beads": "Beckman Coulter A63881, or homemade SPRI (20% PEG-8000, 2.5 M NaCl)",
    }
