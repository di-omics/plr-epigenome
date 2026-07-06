"""Tests for the NEBNext Ultra II DNA + UMI end-to-end protocol (no hardware)."""

import asyncio

from tipseq_plr.protocols.dna_ultra2_umi.config import (
    Ultra2Config, adaptor_dilution, pcr_cycles_for,
)
from tipseq_plr.protocols.dna_ultra2_umi.protocol import Ultra2DnaUmi


def _cfg(**kw):
    cfg = Ultra2Config(simulate=True, **kw)
    setattr(cfg, "_sim_time_scale", 0.0)
    return cfg


def test_adaptor_dilution_table():
    assert adaptor_dilution(500)[0] == "none"     # 1 ug - 101 ng: undiluted
    assert adaptor_dilution(50)[0] == "1:10"      # 100 - 5 ng
    assert adaptor_dilution(1)[0] == "1:50"       # < 5 ng


def test_pcr_cycles_scale_with_input():
    assert pcr_cycles_for(500) == 3
    assert pcr_cycles_for(50) == 4
    assert pcr_cycles_for(5) == 8
    assert pcr_cycles_for(0.5) == 11
    # lower input -> more cycles, monotonically
    cyc = [pcr_cycles_for(x) for x in (500, 100, 50, 10, 5, 1, 0.5)]
    assert cyc == sorted(cyc)


def test_cycles_override():
    assert _cfg(input_ng=100, pcr_cycles_override=12).cycles() == 12
    assert _cfg(input_ng=100).cycles() == 3


def test_pool_plan_normalizes_passing_wells():
    proto = Ultra2DnaUmi(_cfg(num_samples=8, pool_target_ng_per_ul=2.0, pool_final_ul=30.0))
    wells = [
        {"well": "A1", "ng_per_ul": 20.0, "verdict": "pass"},    # 60 ng target -> 3 uL sample
        {"well": "B1", "ng_per_ul": 0.1, "verdict": "fail"},     # excluded
        {"well": "C1", "ng_per_ul": 1.0, "verdict": "pass"},     # need 60 uL, capped at 30
    ]
    plan = {p["well"]: p for p in proto._pool_plan(wells)}
    assert abs(plan["A1"]["sample_ul"] - 3.0) < 1e-6
    assert abs(plan["A1"]["water_ul"] - 27.0) < 1e-6
    assert plan["B1"]["action"] == "exclude" and plan["B1"]["sample_ul"] == 0.0
    assert plan["C1"]["sample_ul"] == 30.0     # low-conc well capped at final volume


def test_end_to_end_cleanup_path():
    report = asyncio.run(Ultra2DnaUmi(_cfg(num_samples=96, input_ng=100)).run())
    assert report["validation_tier"] == "untested"
    assert report["pcr_cycles"] == 3
    assert sum(report["counts"].values()) == 96
    assert len(report["pool_plan"]) == 96
    assert report["tapestation"].startswith("manual")


def test_end_to_end_size_select_path():
    report = asyncio.run(Ultra2DnaUmi(_cfg(num_samples=24, input_ng=500, size_select=True)).run())
    assert sum(report["counts"].values()) == 24
    assert len(report["pool_plan"]) == 24


def test_vision_clean_run_completes():
    report = asyncio.run(Ultra2DnaUmi(_cfg(num_samples=8, vision_enabled=True)).run())
    assert report["status"] == "complete"
    assert report["vision_faults"] == 0
    assert report["vision_log"]                       # checkpoints actually ran


def test_vision_fault_aborts_before_qc():
    from tipseq_plr.steps.vision import CHECK_BEAD_PELLET
    cfg = _cfg(num_samples=8, vision_enabled=True, vision_fault_at=(CHECK_BEAD_PELLET,))
    report = asyncio.run(Ultra2DnaUmi(cfg).run())
    assert report["status"] == "aborted"
    assert "bead_pellet" in report["vision_fault"]
    assert report["counts"] == {"pass": 0, "dilute": 0, "fail": 0}   # never reached QC
    assert report["vision_faults"] >= 1


def test_vision_monitor_only_does_not_abort():
    from tipseq_plr.steps.vision import CHECK_NOT_OVERDRIED
    cfg = _cfg(num_samples=8, vision_enabled=True, vision_abort_on_fault=False,
               vision_fault_at=(CHECK_NOT_OVERDRIED,))
    report = asyncio.run(Ultra2DnaUmi(cfg).run())
    assert report["status"] == "complete"             # monitor-only: logged, not aborted
    assert report["vision_faults"] >= 1
    assert sum(report["counts"].values()) == 8         # QC still ran
