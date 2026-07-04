"""
Shared data model for the FACSMelody reverse-engineering toolkit.

These types are the contract between the RE stages (discover -> capture ->
correlate -> decode -> replay) and the runtime backend (`backends/bd_facsmelody`).
The whole point of the toolkit is to *produce a `ProtocolMap`*; once it exists and
is trusted, the backend loads it and the FACS step becomes a normal device call.

Nothing here imports hardware libraries, so this module is always importable.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional


class Transport(str, Enum):
    USB = "usb"          # PyUSB bulk/interrupt endpoints
    SERIAL = "serial"    # pyserial COM/tty
    TCP = "tcp"          # raw TCP socket (some BD carts expose an Ethernet link)
    UNKNOWN = "unknown"


@dataclass
class Endpoint:
    """A candidate communication endpoint found during discovery."""

    transport: Transport
    address: str                       # e.g. "usb:0x1fbd:0x0002", "COM4", "10.0.0.5:9100"
    description: str = ""
    vendor: str = ""
    product: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class CaptureFrame:
    """One observed frame on the OEM<->device link (either direction)."""

    ts: float                          # monotonic-ish timestamp (seconds)
    direction: str                     # "out" (host->device) or "in" (device->host)
    data: bytes
    source: str = ""                   # "usbpcap", "usbmon", "chorus-log", ...

    def hex(self) -> str:
        return self.data.hex()


@dataclass
class ActionMark:
    """A human-labeled instant: 'I clicked Start Sort now'. Used to slice the
    capture into action-aligned windows during correlation (Rick's step: perform
    one discrete OEM action, see what bytes it produced)."""

    ts: float
    label: str
    note: str = ""


@dataclass
class Command:
    """A decoded, replayable command in the Melody protocol.

    `frame_template` is the bytes to send, with `{param}` placeholders filled by
    `params` encoders at send time. `response` is a regex (on hex or ascii) that
    confirms success. Everything is Optional until decoding fills it in - an
    undecoded Command still documents intent, which keeps the backend honest.
    """

    name: str                          # logical name, e.g. "start_sort"
    transport: Transport = Transport.UNKNOWN
    frame_template: Optional[str] = None   # hex string, may contain {param} tokens
    response_regex: Optional[str] = None
    params: Dict[str, str] = field(default_factory=dict)   # param -> encoder spec
    terminator: Optional[str] = None       # hex of frame terminator if any
    checksum: Optional[str] = None         # checksum scheme name if any
    evidence: List[str] = field(default_factory=list)      # capture frame refs
    decoded: bool = False
    notes: str = ""


@dataclass
class ProtocolMap:
    """The deliverable: everything needed to drive the Melody headlessly."""

    device: str = "BD FACSMelody"
    transport: Transport = Transport.UNKNOWN
    endpoint: Optional[str] = None
    commands: Dict[str, Command] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    notes: str = ""

    # -- persistence ---------------------------------------------------------
    def to_json(self, path: str):
        payload = {
            "device": self.device,
            "transport": self.transport.value,
            "endpoint": self.endpoint,
            "created": self.created,
            "notes": self.notes,
            "commands": {
                name: {**asdict(c), "transport": c.transport.value}
                for name, c in self.commands.items()
            },
        }
        with open(path, "w") as fh:
            json.dump(payload, fh, indent=2)

    @classmethod
    def from_json(cls, path: str) -> "ProtocolMap":
        with open(path) as fh:
            d = json.load(fh)
        pm = cls(
            device=d.get("device", "BD FACSMelody"),
            transport=Transport(d.get("transport", "unknown")),
            endpoint=d.get("endpoint"),
            created=d.get("created", time.time()),
            notes=d.get("notes", ""),
        )
        for name, c in d.get("commands", {}).items():
            c = dict(c)
            c["transport"] = Transport(c.get("transport", "unknown"))
            pm.commands[name] = Command(**c)
        return pm

    def coverage(self) -> dict:
        total = len(self.commands)
        done = sum(1 for c in self.commands.values() if c.decoded)
        return {"decoded": done, "total": total,
                "missing": [n for n, c in self.commands.items() if not c.decoded]}


# The minimum command set the sciTIP-seq FACS step needs. We seed a ProtocolMap
# with these as *undecoded* placeholders so the RE work has an explicit target
# list and the backend can report exactly what still blocks a live run.
REQUIRED_COMMANDS = [
    ("connect",        "open the control link / handshake with the cart"),
    ("get_status",     "poll instrument state (idle/running/clog/error)"),
    ("load_template",  "select a pre-built sort experiment/gate template by name"),
    ("set_deposition", "set plate format + target cells-per-well for sort-to-plate"),
    ("prime",          "prime fluidics / start stream, verify break-off stable"),
    ("start_sort",     "begin depositing into the staged plate"),
    ("wait_complete",  "block/poll until the plate is fully sorted"),
    ("abort",          "emergency stop the sort"),
    ("clean",          "run the clean/flush cycle between samples"),
]


def seed_required(device: str = "BD FACSMelody") -> ProtocolMap:
    pm = ProtocolMap(device=device)
    for name, note in REQUIRED_COMMANDS:
        pm.commands[name] = Command(name=name, notes=note, decoded=False)
    return pm
