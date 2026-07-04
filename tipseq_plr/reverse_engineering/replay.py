"""
Stage 6 of the RE playbook: replay decoded commands to confirm them.

This is where reverse engineering meets a Class 1/3B-laser cell sorter with
pressurized fluidics, so the defaults are deliberately timid:

  * DRY-RUN by default. `send()` logs the exact bytes and returns without
    transmitting unless the client was constructed with `armed=True` AND the call
    passes `live=True`. Two independent switches, both off by default.
  * Confirm *read-only* commands (get_status) before anything actuating.
  * Never auto-send anything that moves fluid, opens a nozzle, or fires a sort
    without a human in the loop. `ACTUATING` commands require `allow_actuation`.

Reverse-engineering an instrument you own for interoperability is fine; doing it
to a live sorter carelessly is how you aerosolize a sample. Keep the guards.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Optional

from .model import Transport

logger = logging.getLogger("melody.re.replay")

# Commands that physically actuate the instrument - gated behind allow_actuation.
ACTUATING = {"prime", "start_sort", "clean", "set_deposition"}


class ReplayClient:
    def __init__(self, transport: Transport, endpoint: str, *,
                 armed: bool = False, allow_actuation: bool = False,
                 read_timeout: float = 1.0):
        self.transport = transport
        self.endpoint = endpoint
        self.armed = armed
        self.allow_actuation = allow_actuation
        self.read_timeout = read_timeout
        self._conn = None

    # -- connection ----------------------------------------------------------
    def open(self):
        if not self.armed:
            logger.warning("ReplayClient DRY-RUN (armed=False): will not open %s", self.endpoint)
            return
        if self.transport == Transport.TCP:
            host, port = self.endpoint.rsplit(":", 1)
            self._conn = socket.create_connection((host, int(port)), timeout=self.read_timeout)
        elif self.transport == Transport.SERIAL:
            import serial
            self._conn = serial.Serial(self.endpoint, timeout=self.read_timeout)
        elif self.transport == Transport.USB:
            self._conn = _UsbConn(self.endpoint, self.read_timeout)
            self._conn.open()
        else:
            raise ValueError(f"unknown transport {self.transport}")
        logger.info("ReplayClient opened %s (%s)", self.endpoint, self.transport.value)

    def close(self):
        try:
            if self._conn is not None:
                self._conn.close()
        finally:
            self._conn = None

    # -- send ----------------------------------------------------------------
    def send(self, name: str, frame_hex: str, *, live: bool = False,
             expect: Optional[bytes] = None) -> Optional[bytes]:
        data = bytes.fromhex(frame_hex)
        if name in ACTUATING and not self.allow_actuation:
            raise PermissionError(
                f"'{name}' actuates the sorter; construct ReplayClient with "
                f"allow_actuation=True and a human present to send it.")
        if not (self.armed and live):
            logger.warning("[dry-run] would send '%s': %s", name, frame_hex)
            return None
        if self._conn is None:
            self.open()
        logger.info("SEND '%s': %s", name, frame_hex)
        self._conn.write(data)
        resp = self._conn.read()
        logger.info("RECV: %s", resp.hex() if resp else "<none>")
        if expect is not None and resp is not None and expect not in resp:
            logger.warning("response did not contain expected %s", expect.hex())
        return resp


class _UsbConn:
    """Minimal PyUSB bulk endpoint wrapper, matching Rick's PyUSB-based approach.
    Endpoint format: 'usb:0xVID:0xPID'. Endpoints auto-detected as first bulk
    OUT/IN pair; override if the Melody uses interrupt endpoints."""

    def __init__(self, endpoint: str, timeout: float):
        self.endpoint = endpoint
        self.timeout_ms = int(timeout * 1000)
        self.dev = None
        self.ep_out = None
        self.ep_in = None

    def open(self):
        import usb.core
        import usb.util
        _, vid, pid = self.endpoint.split(":")
        self.dev = usb.core.find(idVendor=int(vid, 16), idProduct=int(pid, 16))
        if self.dev is None:
            raise RuntimeError(f"USB device {self.endpoint} not found")
        try:
            self.dev.set_configuration()
        except Exception:
            pass
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]
        self.ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        self.ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)

    def write(self, data: bytes):
        self.ep_out.write(data, timeout=self.timeout_ms)

    def read(self, size: int = 512) -> bytes:
        try:
            return bytes(self.ep_in.read(size, timeout=self.timeout_ms))
        except Exception:
            return b""

    def close(self):
        import usb.util
        if self.dev is not None:
            usb.util.dispose_resources(self.dev)
