"""
Stage 1 of the RE playbook: find the link.

Rick's first move on any instrument is "what does it even talk over?" Before you
can sniff traffic you need to know whether the Melody presents as USB, serial, or
an Ethernet cart. This module enumerates all three so you can spot the device by
plugging/unplugging and diffing the list.

All hardware libs are optional; missing ones just yield no candidates of that
transport rather than crashing.
"""

from __future__ import annotations

import logging
import socket
from typing import List, Optional

from .model import Endpoint, Transport

logger = logging.getLogger("melody.re.discover")

# Known/guessed BD USB vendor IDs to highlight (BD Biosciences has used 0x1fbd
# and OEM IDs). Highlighting is a hint only - confirm by unplug/replug diff.
BD_VENDOR_HINTS = {0x1FBD: "BD Biosciences (observed)", 0x0483: "ST/OEM MCU (common in carts)"}


def list_usb() -> List[Endpoint]:
    try:
        import usb.core
        import usb.util
    except Exception as e:
        logger.info("pyusb not available (%s); skipping USB enumeration.", e)
        return []
    out: List[Endpoint] = []
    for dev in usb.core.find(find_all=True):
        try:
            vid, pid = dev.idVendor, dev.idProduct
            manuf = _safe_str(dev, "iManufacturer")
            prod = _safe_str(dev, "iProduct")
            hint = BD_VENDOR_HINTS.get(vid, "")
            out.append(Endpoint(
                transport=Transport.USB,
                address=f"usb:{vid:#06x}:{pid:#06x}",
                description=(hint or "").strip(),
                vendor=manuf or f"{vid:#06x}",
                product=prod or f"{pid:#06x}",
                extra={"bus": getattr(dev, "bus", None), "address": getattr(dev, "address", None),
                       "vid": vid, "pid": pid, "bd_hint": bool(hint)},
            ))
        except Exception as e:  # some devices refuse descriptor reads without a driver
            logger.debug("skip usb dev: %s", e)
    return out


def list_serial() -> List[Endpoint]:
    try:
        from serial.tools import list_ports
    except Exception as e:
        logger.info("pyserial not available (%s); skipping serial enumeration.", e)
        return []
    out = []
    for p in list_ports.comports():
        out.append(Endpoint(
            transport=Transport.SERIAL,
            address=p.device,
            description=p.description or "",
            vendor=(p.manufacturer or ""),
            product=(p.product or ""),
            extra={"vid": p.vid, "pid": p.pid, "serial_number": p.serial_number},
        ))
    return out


def probe_tcp(host: str, ports=(9100, 9600, 8000, 8080, 5025, 62000), timeout=0.4) -> List[Endpoint]:
    """Some BD carts expose a raw-socket control port over Ethernet. Probe a host
    for a few likely control ports. Only scans the single host you name - this is
    interoperability recon on your own instrument, not a network sweep."""
    out = []
    for port in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            if s.connect_ex((host, port)) == 0:
                out.append(Endpoint(
                    transport=Transport.TCP, address=f"{host}:{port}",
                    description="open TCP control-port candidate",
                    extra={"host": host, "port": port},
                ))
        finally:
            s.close()
    return out


def discover(tcp_host: Optional[str] = None) -> List[Endpoint]:
    eps = list_usb() + list_serial()
    if tcp_host:
        eps += probe_tcp(tcp_host)
    logger.info("discovered %d endpoint(s)", len(eps))
    return eps


def diff(before: List[Endpoint], after: List[Endpoint]) -> List[Endpoint]:
    """Endpoints present in `after` but not `before` - the unplug/replug trick to
    isolate the instrument's own link."""
    keys = {e.address for e in before}
    return [e for e in after if e.address not in keys]


def _safe_str(dev, attr) -> Optional[str]:
    try:
        import usb.util
        idx = getattr(dev, attr)
        return usb.util.get_string(dev, idx) if idx else None
    except Exception:
        return None
