"""Smoke + logic tests that run without PyLabRobot installed (dry/stub mode)."""

import asyncio

import pytest

from tipseq_plr import Method, RunConfig, TipSeqProtocol
from tipseq_plr.backends import InhecoODTCBackend
from tipseq_plr.deck import build_deck
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


def test_reagent_source_uses_one_well_per_star_channel():
    """A shared reagent must not model an 8 mm well as an eight-channel trough."""
    from tipseq_plr import config as C

    wells = ReagentRegistry.build().resource_for(build_deck(), C.WATER)
    assert len(wells) == 8
    assert len({well.name for well in wells}) == 8


def test_odtc_accepts_a_standard_plr_protocol():
    from pylabrobot.thermocycling.standard import Protocol, Stage, Step

    async def go():
        backend = InhecoODTCBackend(simulate=True)
        await backend.setup()
        await backend.run_protocol(
            Protocol(stages=[Stage(steps=[Step(temperature=[55.0], hold_seconds=1)], repeats=2)]),
            block_max_volume=50.0,
        )
        assert await backend.get_total_step_count() == 2
        await backend.stop()

    asyncio.run(go())


def test_loadout_lists_reagents():
    plan = TipSeqProtocol(_cfg(Method.PLATE_TIPSEQ)).loadout()
    assert "reagents" in plan and "labware" in plan
    assert "spri_beads" in plan["reagents"]
    assert plan["reagents"]["spri_beads"]["total_uL"] > 0
