"""Tests for the plate-normalization protocol (no hardware)."""

import asyncio

from tipseq_plr.protocols.normalization import NormConfig, PlateNormalization, build_plan, plan_well
from tipseq_plr.protocols.normalization.plan import summarize


def _cfg(**kw):
    cfg = NormConfig(simulate=True, **kw)
    setattr(cfg, "_sim_time_scale", 0.0)
    return cfg


def test_in_range_well_hits_target_exactly():
    cfg = _cfg(target_ng_per_ul=1.0, final_volume_ul=20.0)  # usable = 12-2-1 = 9 uL
    w = plan_well("A1", conc=10.0, cfg=cfg)                  # need 20 ng -> 2 uL sample
    assert w.status == "ok"
    assert abs(w.sample_ul - 2.0) < 1e-6
    assert abs(w.water_ul - 18.0) < 1e-6
    assert abs(w.final_ng_per_ul - 1.0) < 1e-6


def test_dilute_well_is_capped():
    cfg = _cfg(target_ng_per_ul=5.0, final_volume_ul=20.0)  # need 100 ng
    w = plan_well("B2", conc=1.0, cfg=cfg)                   # need 100 uL, only 9 usable
    assert w.status == "capped_low"
    assert abs(w.sample_ul - cfg.usable_source_ul) < 1e-6
    assert w.final_ng_per_ul < cfg.target_ng_per_ul


def test_concentrated_well_flags_predilution():
    cfg = _cfg(target_ng_per_ul=1.0, final_volume_ul=20.0, min_transfer_ul=1.0)
    w = plan_well("C3", conc=100.0, cfg=cfg)                 # need 0.2 uL < 1 uL min
    assert w.status == "needs_predilution"
    assert w.sample_ul == cfg.min_transfer_ul


def test_empty_well():
    w = plan_well("D4", conc=0.0, cfg=_cfg())
    assert w.status == "empty" and w.sample_ul == 0.0


def test_volume_conservation():
    cfg = _cfg(target_ng_per_ul=1.0, final_volume_ul=20.0)
    for conc in (0.0, 0.5, 2.0, 10.0, 50.0, 200.0):
        w = plan_well("E5", conc=conc, cfg=cfg)
        assert abs((w.sample_ul + w.water_ul) - cfg.final_volume_ul) < 1e-6


def test_end_to_end_simulation():
    report = asyncio.run(PlateNormalization(_cfg(num_samples=96)).run())
    assert report["wells"] == 96
    assert sum(report["counts"].values()) == 96
    assert report["total_sample_ul"] > 0


def test_summarize_counts():
    cfg = _cfg(target_ng_per_ul=1.0, final_volume_ul=20.0)
    concs = {"A1": 10.0, "A2": 0.5, "A3": 100.0, "A4": 0.0}
    s = summarize(build_plan(concs, cfg))
    assert s["counts"]["ok"] == 1
    assert s["counts"]["capped_low"] == 1
    assert s["counts"]["needs_predilution"] == 1
    assert s["counts"]["empty"] == 1
