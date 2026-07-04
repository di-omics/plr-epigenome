"""Tests for the CUT&Tag protocol (no hardware)."""

import asyncio

from tipseq_plr.config import Method
from tipseq_plr.protocols.cut_and_tag import CutAndTag, CutAndTagConfig


def _cfg(**kw):
    cfg = CutAndTagConfig(simulate=True, **kw)
    setattr(cfg, "_sim_time_scale", 0.0)
    return cfg


def test_end_to_end_simulation():
    report = asyncio.run(CutAndTag(_cfg(num_samples=96)).run())
    assert report["method"] == "cut_and_tag"
    assert report["samples"] == 96
    assert sum(report["counts"].values()) == 96


def test_run_config_uses_cut_and_tag_method_and_cycles():
    rc = _cfg(num_samples=24, pcr_cycles=15).to_run_config()
    assert rc.method == Method.CUT_AND_TAG
    assert rc.num_samples == 24
    assert rc.pcr.cycles == 15                    # propagated to the PCR profile


def test_qc_count_scales_with_samples():
    for n, cols in ((8, 1), (24, 3), (96, 12)):
        report = asyncio.run(CutAndTag(_cfg(num_samples=n)).run())
        assert sum(report["counts"].values()) == cols * 8


def test_no_facs_boundary():
    # CUT&Tag keeps cells on conA beads; it must never invoke a sorter/FACS pause.
    proto = CutAndTag(_cfg(num_samples=8))
    assert proto.devices.sorter is None
