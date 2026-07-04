"""Smoke + logic tests that run without PyLabRobot installed (dry/stub mode)."""

import asyncio

import pytest

from tipseq_plr import Method, RunConfig, TipSeqProtocol
from tipseq_plr.reagents import ReagentRegistry
from tipseq_plr.steps.qc import _least_squares


def _cfg(method, samples=96):
    cfg = RunConfig(method=method, num_samples=samples, simulate=True)
    setattr(cfg, "_sim_time_scale", 0.0)
    return cfg


@pytest.mark.parametrize("method", [Method.PLATE_TIPSEQ, Method.BULK_TIPSEQ, Method.SCITIP_SEQ])
def test_run_end_to_end(method):
    report = asyncio.run(TipSeqProtocol(_cfg(method)).run())
    assert report["method"] == method.value
    c = report["counts"]
    assert c["pass"] + c["dilute"] + c["fail"] == 96


@pytest.mark.parametrize("samples,cols", [(8, 1), (24, 3), (48, 6), (96, 12)])
def test_qc_well_count_scales(samples, cols):
    report = asyncio.run(TipSeqProtocol(_cfg(Method.PLATE_TIPSEQ, samples)).run())
    total = sum(report["counts"].values())
    assert total == cols * 8


def test_least_squares_recovers_line():
    xs = [0, 1, 2, 3, 4]
    ys = [1 + 2 * x for x in xs]
    m, b = _least_squares(xs, ys)
    assert abs(m - 2) < 1e-9 and abs(b - 1) < 1e-9


def test_reagent_dead_volume_guard():
    reg = ReagentRegistry.build()
    from tipseq_plr import config as C

    reg.declare_loaded(C.WATER, 100.0)
    reg.charge(C.WATER, 40.0)                 # ok: 60 left
    with pytest.raises(RuntimeError):
        reg.charge(C.WATER, 50.0)             # would leave 10 < 20 dead volume


def test_loadout_lists_reagents():
    plan = TipSeqProtocol(_cfg(Method.PLATE_TIPSEQ)).loadout()
    assert "reagents" in plan and "labware" in plan
    assert "spri_beads" in plan["reagents"]
    assert plan["reagents"]["spri_beads"]["total_uL"] > 0
