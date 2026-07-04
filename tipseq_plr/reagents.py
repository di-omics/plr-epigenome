"""
Reagent map: logical reagent name -> physical reservoir well on the deck.

Buffers live in the `buffers` reagent carrier (room temperature); enzymes and
temperature-sensitive mixes live in the `enzymes` carrier, which should sit on a
chilled position (e.g. Inheco CPAC) for a real run.

The registry also tracks a running volume estimate per reagent so a pre-flight
check can tell the operator how much of each to load, and so a run aborts early
if a reservoir would be drawn below dead volume rather than aspirating air.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config as C


# reagent -> (carrier, reservoir_index, column). Column 'A1'..'H1' style address
# is resolved against the reservoir plate at access time.
_LAYOUT = {
    # buffers carrier (reservoir plate index, column letter, rows used)
    C.WASH_BUFFER:     ("buffers", 0, "1"),
    C.ANTIBODY_BUFFER: ("buffers", 0, "2"),
    C.DIG_WASH:        ("buffers", 0, "3"),
    C.DIG_300:         ("buffers", 0, "4"),
    C.TAG_BUFFER:      ("buffers", 0, "5"),
    C.SPRI_BEADS:      ("buffers", 1, "1"),
    C.ETHANOL_80:      ("buffers", 1, "2"),
    C.WATER:           ("buffers", 1, "3"),
    C.EDTA_0_5M:       ("buffers", 1, "4"),
    C.SDS_10:          ("buffers", 1, "5"),
    C.GUHCL:           ("buffers", 1, "6"),
    C.CONA_BEADS:      ("buffers", 2, "1"),
    C.QUANT_DYE:       ("buffers", 2, "2"),
    # enzymes carrier (chilled)
    C.PROTEINASE_K:    ("enzymes", 0, "1"),
    C.TAQ_5X:          ("enzymes", 0, "2"),
    C.T7_NTP:          ("enzymes", 0, "3"),
    C.T7_BUFFER:       ("enzymes", 0, "4"),
    C.T7_POLYMERASE:   ("enzymes", 0, "5"),
    C.RNASE_INHIBITOR: ("enzymes", 0, "6"),
    C.RANDOM_HEXAMER:  ("enzymes", 1, "1"),
    C.RT_BUFFER_5X:    ("enzymes", 1, "2"),
    C.DNTP_10MM:       ("enzymes", 1, "3"),
    C.DTT_100MM:       ("enzymes", 1, "4"),
    C.MMLV_RT:         ("enzymes", 1, "5"),
    C.RNASE_H:         ("enzymes", 1, "6"),
    C.SSS_PRIMER:      ("enzymes", 2, "1"),
    C.TAPS_BUFFER:     ("enzymes", 2, "2"),
    C.TN5_MEB:         ("enzymes", 2, "3"),
    C.PCR_MASTERMIX:   ("enzymes", 2, "4"),
    C.INDEX_I5:        ("enzymes", 3, "1"),  # i5 lives in an index plate for sci
    C.INDEX_I7:        ("enzymes", 3, "2"),
}

_DEAD_VOLUME_UL = 20.0     # per reservoir well, don't aspirate below this
_RESERVOIR_MAX_UL = 2000.0


@dataclass
class Reagent:
    name: str
    carrier: str
    reservoir_index: int
    column: str
    required_ul: float = 0.0    # accumulated by plan_load -> prep sheet
    loaded_ul: float = 0.0      # physically loaded by operator (0 = undeclared)
    consumed_ul: float = 0.0    # accumulated by charge during the run

    @property
    def remaining_ul(self) -> float:
        return self.loaded_ul - self.consumed_ul


@dataclass
class ReagentRegistry:
    reagents: dict = field(default_factory=dict)

    @classmethod
    def build(cls) -> "ReagentRegistry":
        reg = cls()
        for name, (carrier, idx, col) in _LAYOUT.items():
            reg.reagents[name] = Reagent(name, carrier, idx, col)
        return reg

    def resource_for(self, deckmap, name: str):
        """Return the PLR well resource for a reagent, e.g. reservoir['A1'].

        The column letter in the layout indexes a *column* of the reservoir
        plate; row A of that column is used as the pickup well. For high-throughput
        buffer dispensing across a 96-well plate you would use the whole column;
        here we keep it simple and draw from row A.
        """
        r = self.reagents[name]
        carrier = deckmap.reagent_troughs if r.carrier == "buffers" else deckmap.enzyme_troughs
        reservoir = carrier[r.reservoir_index]
        return reservoir[f"A{r.column}"]

    def declare_loaded(self, name: str, volume_ul: float):
        """Operator preflight: state how much of a reagent is physically in the
        reservoir. Only then does `charge` enforce the dead-volume guard."""
        self.reagents[name].loaded_ul = volume_ul

    def charge(self, name: str, volume_ul: float, wells: int = 1):
        """Record consumption; raise only if a declared reservoir would draw
        below dead volume (no-op guard when the load is undeclared, e.g. sim)."""
        r = self.reagents[name]
        total = volume_ul * wells
        if r.loaded_ul > 0 and (r.remaining_ul - total) < _DEAD_VOLUME_UL:
            raise RuntimeError(
                f"Reagent '{name}' would drop below dead volume "
                f"({r.remaining_ul:.0f} uL left, need {total:.0f} uL). Reload before run."
            )
        r.consumed_ul += total

    def plan_load(self, name: str, volume_ul: float, wells: int = 1):
        """Pre-flight: accumulate the required volume for the prep sheet."""
        self.reagents[name].required_ul += volume_ul * wells

    def loadout(self) -> dict:
        """Human-readable 'prepare this much of each reagent' table.

        `prepare_uL` is per reservoir well (capped at the well's working volume);
        `reservoirs_needed` says how many wells/troughs to fill for the whole run.
        """
        out = {}
        for name, r in self.reagents.items():
            if r.required_ul <= 0:
                continue
            need = r.required_ul * 1.10 + _DEAD_VOLUME_UL   # 10% overage + dead vol
            reservoirs = max(1, int(need // _RESERVOIR_MAX_UL) + 1)
            out[name] = {
                "carrier": r.carrier,
                "reservoir": r.reservoir_index,
                "column": r.column,
                "total_uL": round(need, 1),
                "prepare_uL_per_reservoir": round(min(need, _RESERVOIR_MAX_UL), 1),
                "reservoirs_needed": reservoirs,
            }
        return out
