"""
Stage 3 of the RE playbook: capture the OEM <-> device traffic.

You capture with the platform's standard sniffer while driving Chorus by hand:

  * Windows: Wireshark + USBPcap on the Melody's USB interface (export .pcapng)
  * Linux  : `usbmon` (cat /sys/kernel/debug/usb/usbmon/Nu > cap.mon) or Wireshark
  * Serial : a COM port sniffer, or a hardware TAP, saved as hex-per-line

This module doesn't reimplement a sniffer - it *ingests* those captures into a
uniform `list[CaptureFrame]` so the correlation and decode stages are
transport-agnostic. Parsers use pyshark/scapy when present and fall back to a
tolerant hex-line reader that needs no dependencies.
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional

from .model import CaptureFrame

logger = logging.getLogger("melody.re.capture")


def from_pcap(path: str, usb_only: bool = True) -> List[CaptureFrame]:
    """Parse a Wireshark/USBPcap capture. Prefers pyshark, falls back to scapy."""
    frames = _from_pcap_pyshark(path, usb_only)
    if frames is not None:
        return frames
    frames = _from_pcap_scapy(path, usb_only)
    if frames is not None:
        return frames
    raise RuntimeError(
        "Need pyshark or scapy to parse pcap. `pip install pyshark` (requires "
        "tshark) or `pip install scapy`, or export the capture as hex lines and "
        "use from_hexdump()."
    )


def _from_pcap_pyshark(path: str, usb_only: bool) -> Optional[List[CaptureFrame]]:
    try:
        import pyshark
    except Exception:
        return None
    frames: List[CaptureFrame] = []
    cap = pyshark.FileCapture(path, include_raw=True, use_json=True)
    try:
        for pkt in cap:
            payload = _extract_usb_payload(pkt)
            if payload is None:
                continue
            data, direction = payload
            frames.append(CaptureFrame(ts=float(getattr(pkt, "sniff_timestamp", time.time())),
                                       direction=direction, data=data, source="pyshark"))
    finally:
        cap.close()
    return frames


def _extract_usb_payload(pkt):
    try:
        usb = getattr(pkt, "usb", None)
        if usb is None:
            return None
        # direction: URB may carry endpoint direction / bus id
        direction = "in" if str(getattr(usb, "endpoint_address_direction", "0")) == "1" else "out"
        raw = None
        for layer in pkt.layers:
            data_field = getattr(layer, "usb_capdata", None) or getattr(layer, "data", None)
            if data_field:
                raw = bytes.fromhex(str(data_field).replace(":", ""))
                break
        if not raw:
            return None
        return raw, direction
    except Exception:
        return None


def _from_pcap_scapy(path: str, usb_only: bool) -> Optional[List[CaptureFrame]]:
    try:
        from scapy.all import rdpcap
    except Exception:
        return None
    frames = []
    for pkt in rdpcap(path):
        raw = bytes(pkt.payload) if hasattr(pkt, "payload") else bytes(pkt)
        if raw:
            frames.append(CaptureFrame(ts=float(getattr(pkt, "time", time.time())),
                                       direction="out", data=raw, source="scapy"))
    return frames


_HEX_LINE = re.compile(r"^\s*(?P<ts>[\d.]+)?\s*(?P<dir>[<>]|in|out|tx|rx)?\s*[:=]?\s*(?P<hex>[0-9a-fA-F\s]+)$")


def from_hexdump(path: str) -> List[CaptureFrame]:
    """Tolerant reader for `<ts> <dir> <hexbytes>` lines (no deps). `>`/`tx`/`out`
    = host->device, `<`/`rx`/`in` = device->host."""
    frames = []
    with open(path, errors="ignore") as fh:
        for line in fh:
            m = _HEX_LINE.match(line)
            if not m or not m.group("hex"):
                continue
            hexs = re.sub(r"\s+", "", m.group("hex"))
            if len(hexs) < 2 or len(hexs) % 2:
                continue
            d = (m.group("dir") or ">").lower()
            direction = "in" if d in ("<", "in", "rx") else "out"
            ts = float(m.group("ts")) if m.group("ts") else time.time()
            try:
                frames.append(CaptureFrame(ts=ts, direction=direction,
                                           data=bytes.fromhex(hexs), source="hexdump"))
            except ValueError:
                continue
    logger.info("read %d frames from hexdump %s", len(frames), path)
    return frames


def from_chorus_log(path: str) -> List[CaptureFrame]:
    """Extract hex byte strings that Chorus itself logged (TX:/RX: style lines).
    Direction inferred from a TX/RX/-> marker on the line."""
    frames = []
    hexrun = re.compile(r"((?:[0-9a-fA-F]{2}[\s:]?){3,})")
    with open(path, errors="ignore") as fh:
        for line in fh:
            m = hexrun.search(line)
            if not m:
                continue
            hexs = re.sub(r"[\s:]", "", m.group(1))
            if len(hexs) % 2:
                hexs = hexs[:-1]
            low = line.lower()
            direction = "in" if ("rx" in low or "recv" in low or "<-" in low) else "out"
            try:
                frames.append(CaptureFrame(ts=time.time(), direction=direction,
                                           data=bytes.fromhex(hexs), source="chorus-log"))
            except ValueError:
                continue
    return frames
