"""
FACSMelody reverse-engineering toolkit.

A staged, transport-agnostic harness that applies Rick Wierenga's PyLabRobot
methodology - work down to the OEM's own command layer, sniff the OEM<->device
traffic, correlate each UI action to its bytes, decode the framing, replay with
PyUSB/serial - to the BD FACSMelody + FACSChorus so the sciTIP-seq FACS step can
be automated. The deliverable is a `ProtocolMap` the runtime backend loads.

Stages (see cli.py): discover -> chorus -> (seed) -> mark -> decode -> replay.
"""

from .model import Command, ProtocolMap, Transport, seed_required, REQUIRED_COMMANDS

__all__ = ["Command", "ProtocolMap", "Transport", "seed_required", "REQUIRED_COMMANDS"]
