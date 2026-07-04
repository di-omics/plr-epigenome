"""
Stage 5 of the RE playbook: decode the framing and build the ProtocolMap.

Given the action-specific frames from correlation, work out the structure:
  * framing      - fixed length? terminator byte(s)? length-prefixed?
  * opcode       - the longest common prefix across a command's frames
  * parameters   - the bytes that vary when you change one thing (cells/well, well)
  * checksum     - brute-force common schemes over candidate byte ranges

None of this assumes BD's specific scheme; it proposes hypotheses and shows their
evidence so a human confirms before anything is replayed to a live sorter.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, List, Optional

from .model import Command, CaptureFrame, ProtocolMap, Transport, seed_required

logger = logging.getLogger("melody.re.decode")


# -- framing -----------------------------------------------------------------
def guess_terminator(frames: List[CaptureFrame]) -> Optional[bytes]:
    """Most common trailing 1-2 bytes across frames - the likely terminator."""
    if not frames:
        return None
    tails1 = Counter(f.data[-1:] for f in frames if f.data)
    tails2 = Counter(f.data[-2:] for f in frames if len(f.data) >= 2)
    best2, n2 = (tails2.most_common(1) or [(b"", 0)])[0]
    best1, n1 = (tails1.most_common(1) or [(b"", 0)])[0]
    # prefer a 2-byte terminator only if it's as dominant as the 1-byte one
    if n2 >= max(2, int(0.6 * len(frames))) and best2 not in (b"\x00\x00",):
        return best2
    if n1 >= max(2, int(0.6 * len(frames))):
        return best1
    return None


def guess_fixed_length(frames: List[CaptureFrame]) -> Optional[int]:
    lens = Counter(len(f.data) for f in frames)
    if lens and lens.most_common(1)[0][1] >= max(2, int(0.8 * len(frames))):
        return lens.most_common(1)[0][0]
    return None


def common_prefix(frames: List[CaptureFrame]) -> bytes:
    datas = [f.data for f in frames if f.data]
    if not datas:
        return b""
    p = datas[0]
    for d in datas[1:]:
        i = 0
        while i < len(p) and i < len(d) and p[i] == d[i]:
            i += 1
        p = p[:i]
        if not p:
            break
    return p


# -- checksums ---------------------------------------------------------------
def _crc16_ccitt(data: bytes, poly=0x1021, init=0xFFFF) -> int:
    crc = init
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


def _crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc


def checksum_candidates(frame: bytes, terminator: bytes = b"") -> List[str]:
    """Return names of checksum schemes whose value over the body matches the
    trailing checksum bytes. Tests sum8/xor8 (1 byte) and CRC16 variants (2
    bytes). If a `terminator` is present it is stripped first, since checksums
    commonly sit *before* the terminator."""
    if terminator and frame.endswith(terminator):
        frame = frame[: -len(terminator)]
    hits = []
    if len(frame) >= 2:
        body, chk = frame[:-1], frame[-1]
        if sum(body) & 0xFF == chk:
            hits.append("sum8")
        x = 0
        for b in body:
            x ^= b
        if x == chk:
            hits.append("xor8")
    if len(frame) >= 3:
        body, chk = frame[:-2], frame[-2:]
        le = int.from_bytes(chk, "little")
        be = int.from_bytes(chk, "big")
        for name, fn in (("crc16-ccitt", _crc16_ccitt), ("crc16-modbus", _crc16_modbus)):
            v = fn(body)
            if v == le:
                hits.append(f"{name}/le")
            if v == be:
                hits.append(f"{name}/be")
    return hits


# -- assembly ----------------------------------------------------------------
def build_command(name: str, frames: List[CaptureFrame], transport: Transport,
                  notes: str = "") -> Command:
    if not frames:
        return Command(name=name, transport=transport, decoded=False, notes=notes)
    term = guess_terminator(frames)
    prefix = common_prefix(frames)
    # pick the most representative frame (the modal length one)
    rep = sorted(frames, key=lambda f: len(f.data))[len(frames) // 2]
    cks = checksum_candidates(rep.data, terminator=term or b"")
    cmd = Command(
        name=name,
        transport=transport,
        frame_template=rep.data.hex(),
        terminator=term.hex() if term else None,
        checksum=cks[0] if cks else None,
        evidence=[f.hex() for f in frames[:8]],
        decoded=True,
        notes=(notes + (f" | opcode~{prefix.hex()}" if prefix else "")).strip(" |"),
    )
    logger.info("decoded '%s': %d frames, term=%s, checksum=%s, opcode~%s",
                name, len(frames), cmd.terminator, cmd.checksum, prefix.hex())
    return cmd


def assemble_protocol(unique_windows: Dict[str, List[CaptureFrame]],
                      transport: Transport,
                      endpoint: Optional[str] = None,
                      base: Optional[ProtocolMap] = None) -> ProtocolMap:
    """Fold decoded commands into a ProtocolMap seeded with the required set, so
    the result explicitly reports which required commands remain undecoded."""
    pm = base or seed_required()
    pm.transport = transport
    pm.endpoint = endpoint
    for label, frames in unique_windows.items():
        if frames:
            note = pm.commands[label].notes if label in pm.commands else ""
            pm.commands[label] = build_command(label, frames, transport, notes=note)
    cov = pm.coverage()
    logger.info("protocol coverage: %d/%d decoded; missing=%s",
                cov["decoded"], cov["total"], cov["missing"])
    return pm
