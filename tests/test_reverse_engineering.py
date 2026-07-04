"""Tests for the FACSMelody RE toolkit + sorter integration (no hardware)."""

import asyncio

import pytest

from tipseq_plr import Method, RunConfig, TipSeqProtocol
from tipseq_plr.reverse_engineering import ProtocolMap, Transport, seed_required
from tipseq_plr.reverse_engineering.model import CaptureFrame
from tipseq_plr.reverse_engineering import decode
from tipseq_plr.reverse_engineering.correlate import CorrelationSession


def _cfg(**kw):
    cfg = RunConfig(method=Method.SCITIP_SEQ, num_samples=96, simulate=True, **kw)
    setattr(cfg, "_sim_time_scale", 0.0)
    return cfg


def test_seed_lists_required_commands():
    pm = seed_required()
    cov = pm.coverage()
    assert cov["total"] == 9 and cov["decoded"] == 0
    assert "start_sort" in pm.commands and not pm.commands["start_sort"].decoded


def test_protocolmap_json_roundtrip(tmp_path):
    pm = seed_required()
    pm.transport = Transport.USB
    pm.endpoint = "usb:0x1fbd:0x0002"
    p = tmp_path / "protocol.json"
    pm.to_json(str(p))
    back = ProtocolMap.from_json(str(p))
    assert back.transport == Transport.USB
    assert set(back.commands) == set(pm.commands)


def test_decode_terminator_prefix_checksum():
    # frames: opcode 0xA5 0x01, payload, sum8 checksum, terminator 0x0d
    def framed(payload):
        body = bytes([0xA5, 0x01]) + payload
        return body + bytes([sum(body) & 0xFF]) + b"\x0d"
    frames = [CaptureFrame(ts=i, direction="out", data=framed(bytes([i])))
              for i in range(5)]
    assert decode.guess_terminator(frames) == b"\x0d"
    assert decode.common_prefix(frames).startswith(b"\xa5\x01")
    # checksum sits before the 0x0d terminator, so pass the terminator to strip it
    cks = decode.checksum_candidates(framed(b"\x07"), terminator=b"\x0d")
    assert "sum8" in cks


def test_correlation_unique_frames_cancels_noise():
    # shared keep-alive appears in both windows; each action has one unique frame
    from tipseq_plr.reverse_engineering.model import ActionMark
    keepalive = b"\x10\x00"
    sess = CorrelationSession(clock=lambda: 100.0)
    sess.marks = [ActionMark(ts=100.0, label="start_sort"),
                  ActionMark(ts=200.0, label="abort")]
    frames = [
        CaptureFrame(ts=100.0, direction="out", data=b"\xaa\x01"),   # unique to start
        CaptureFrame(ts=100.1, direction="out", data=keepalive),
        CaptureFrame(ts=200.0, direction="out", data=b"\xbb\x02"),   # unique to abort
        CaptureFrame(ts=200.1, direction="out", data=keepalive),
    ]
    windows = sess.correlate(frames, pre=0.5, post=0.5)
    unique = sess.unique_frames(windows)
    assert [f.data for f in unique["start_sort"]] == [b"\xaa\x01"]
    assert [f.data for f in unique["abort"]] == [b"\xbb\x02"]


def test_assemble_reports_missing():
    frames = {"start_sort": [CaptureFrame(ts=1, direction="out", data=b"\xaa\x01\x0d")]}
    pm = decode.assemble_protocol(frames, Transport.USB, "usb:0x1:0x2")
    cov = pm.coverage()
    assert pm.commands["start_sort"].decoded
    assert "clean" in cov["missing"]           # untouched commands still flagged


def test_sci_run_with_simulated_sorter():
    cfg = _cfg(sorter_enabled=True)
    report = asyncio.run(TipSeqProtocol(cfg).run())
    assert report["method"] == Method.SCITIP_SEQ.value
    assert sum(report["counts"].values()) == 96


def test_live_sorter_refuses_incomplete_protocol(tmp_path):
    # a seeded (all-undecoded) protocol must not be allowed to drive live hardware
    from tipseq_plr.backends import BDFACSMelodyBackend
    p = tmp_path / "protocol.json"
    seed_required().to_json(str(p))
    be = BDFACSMelodyBackend(protocol_path=str(p), simulate=False)
    with pytest.raises(RuntimeError):
        asyncio.run(be.setup())
