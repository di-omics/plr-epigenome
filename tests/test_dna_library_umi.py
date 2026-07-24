"""Tests for the generic UMI workflow and its fail-closed method boundary."""

import asyncio

import pytest

from tipseq_plr.protocols.dna_library_umi import config as method_config
from tipseq_plr.protocols.dna_library_umi.config import (
    DnaLibraryConfig,
    MethodConfigError,
    load_operator_method,
    operator_method_from_mapping,
    synthetic_demo_method,
)
from tipseq_plr.protocols.dna_library_umi.protocol import DnaLibraryUmi
from tipseq_plr.protocols.dna_library_umi.run import _parse, main


def _cfg(*, size_selection=False, method=None, **kw):
    cfg = DnaLibraryConfig(
        method=method or synthetic_demo_method(size_selection=size_selection),
        simulate=True,
        **kw,
    )
    setattr(cfg, "_sim_time_scale", 0.0)
    return cfg


def _operator_mapping():
    """Arbitrary test data used only to exercise strict schema loading."""

    return {
        "profile_id": "operator-test-fixture",
        "endprep": {
            "input_ul": 11,
            "buffer_ul": 1,
            "enzyme_ul": 1,
            "thermal_steps": [
                {"celsius": 26, "seconds": 2, "name": "test-hold"},
            ],
            "lid_c": 26,
        },
        "ligation": {
            "adaptor_ul": 1,
            "master_mix_ul": 2,
            "enhancer_ul": 1,
            "incubation": {"celsius": 27, "seconds": 2, "name": "test-ligation"},
            "lid_c": 27,
            "mix_cycles": 2,
            "adaptor_preparation": "operator-specified test preparation",
        },
        "cleanup": {
            "bead_ratio": 1.2,
            "elution_ul": 12,
            "transfer_ul": 9,
            "ethanol_washes": 1,
            "ethanol_ul": 21,
        },
        "size_selection": None,
        "pcr": {
            "primer_mix_ul": 1,
            "master_mix_ul": 2,
            "initial_denature": {"celsius": 91, "seconds": 2, "name": "test-initial"},
            "denature": {"celsius": 91, "seconds": 2, "name": "test-denature"},
            "anneal_extend": {"celsius": 51, "seconds": 2, "name": "test-anneal"},
            "final_extend": {"celsius": 51, "seconds": 2, "name": "test-final"},
            "cycles": 4,
            "hold_c": 21,
            "lid_c": 27,
        },
        "pcr_cleanup": {
            "bead_ratio": 1.1,
            "elution_ul": 11,
            "transfer_ul": 8,
            "ethanol_washes": 1,
            "ethanol_ul": 22,
        },
        "timings": {"bead_bind_s": 2, "bead_dry_s": 2},
        "qc": {
            "min_library_ng_per_ul": 0.2,
            "saturation_ng_per_ul": 90,
            "standard_curve_ng": [0, 1, 2, 3, 4, 5, 6, 7],
            "excitation_nm": 480,
            "emission_nm": 520,
        },
        "pooling": {"target_ng_per_ul": 1.5, "final_volume_ul": 12},
    }


def test_method_is_required():
    with pytest.raises(TypeError):
        DnaLibraryConfig()  # type: ignore[call-arg]


def test_no_kit_derived_lookup_helpers_remain():
    assert not hasattr(method_config, "adaptor_dilution")
    assert not hasattr(method_config, "pcr_cycles_for")


def test_synthetic_profile_is_simulation_only():
    with pytest.raises(MethodConfigError, match="cannot be used for a live run"):
        DnaLibraryConfig(method=synthetic_demo_method(), simulate=False)


def test_operator_mapping_is_explicit_and_live_capable():
    method = operator_method_from_mapping(_operator_mapping())
    assert method.profile_id == "operator-test-fixture"
    assert method.synthetic_only is False
    assert method.pcr.cycles == 4
    cfg = DnaLibraryConfig(method=method, num_samples=8, simulate=False)
    assert cfg.method is method


def test_operator_size_selection_has_no_lookup_table():
    raw = _operator_mapping()
    raw["size_selection"] = {
        "first_bead_ul": 5,
        "second_bead_ul": 4,
        "first_magnet_settle_s": 2,
        "second_magnet_settle_s": 3,
        "ethanol_soak_s": 2,
        "final_clear_settle_s": 3,
        "elution_ul": 12,
        "transfer_ul": 9,
        "ethanol_washes": 1,
        "ethanol_ul": 21,
    }
    method = operator_method_from_mapping(raw)
    assert method.size_selection is not None
    assert method.size_selection.first_bead_ul == 5


def test_operator_loader_rejects_missing_and_unknown_fields(tmp_path):
    missing = _operator_mapping()
    del missing["pooling"]
    with pytest.raises(MethodConfigError, match="missing"):
        operator_method_from_mapping(missing)

    unknown = _operator_mapping()
    unknown["recipe_guess"] = 1
    with pytest.raises(MethodConfigError, match="unknown"):
        operator_method_from_mapping(unknown)

    path = tmp_path / "method.json"
    path.write_text("{not json")
    with pytest.raises(MethodConfigError, match="Cannot load"):
        load_operator_method(path)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_operator_mapping_rejects_nonfinite_values(bad_value):
    raw = _operator_mapping()
    raw["cleanup"]["bead_ratio"] = bad_value
    with pytest.raises(MethodConfigError, match="must be finite"):
        operator_method_from_mapping(raw)


def test_operator_loader_round_trip(tmp_path):
    import json

    path = tmp_path / "method.json"
    path.write_text(json.dumps(_operator_mapping()))
    method = load_operator_method(path)
    assert method.endprep.total_ul == 13
    assert method.ligation.total_ul(method.endprep.total_ul) == 17
    assert method.pcr.total_ul(method.cleanup.transfer_ul) == 12


def test_cli_requires_a_profile_and_rejects_synthetic_live():
    with pytest.raises(SystemExit):
        _parse([])
    assert main(["--synthetic-profile", "--no-simulate"]) == 2


def test_pool_plan_uses_profile_values():
    proto = DnaLibraryUmi(_cfg(num_samples=8))
    wells = [
        {"well": "A1", "ng_per_ul": 20.0, "verdict": "pass"},
        {"well": "B1", "ng_per_ul": 0.1, "verdict": "fail"},
        {"well": "C1", "ng_per_ul": 1.0, "verdict": "pass"},
    ]
    plan = {p["well"]: p for p in proto._pool_plan(wells)}
    assert plan["A1"]["sample_ul"] == 0.5
    assert plan["A1"]["water_ul"] == 9.5
    assert plan["B1"]["action"] == "exclude"
    assert plan["C1"]["sample_ul"] == 10.0


def test_end_to_end_synthetic_cleanup_path():
    report = asyncio.run(DnaLibraryUmi(_cfg(num_samples=8)).run())
    assert report["validation_tier"] == "untested"
    assert report["method_profile"] == "synthetic-control-flow-demo"
    assert report["pcr_cycles"] == 2
    assert sum(report["counts"].values()) == 8
    assert len(report["pool_plan"]) == 8
    assert report["fragment_analysis"].startswith("manual")


def test_end_to_end_synthetic_size_selection_path():
    report = asyncio.run(
        DnaLibraryUmi(_cfg(num_samples=8, size_selection=True)).run())
    assert sum(report["counts"].values()) == 8
    assert len(report["pool_plan"]) == 8


def test_vision_clean_run_completes():
    report = asyncio.run(
        DnaLibraryUmi(_cfg(num_samples=8, vision_enabled=True)).run())
    assert report["status"] == "complete"
    assert report["vision_faults"] == 0
    assert report["vision_log"]


def test_vision_fault_aborts_before_qc():
    from tipseq_plr.steps.vision import CHECK_BEAD_PELLET

    cfg = _cfg(
        num_samples=8,
        vision_enabled=True,
        vision_fault_at=(CHECK_BEAD_PELLET,),
    )
    report = asyncio.run(DnaLibraryUmi(cfg).run())
    assert report["status"] == "aborted"
    assert "bead_pellet" in report["vision_fault"]
    assert report["counts"] == {"pass": 0, "dilute": 0, "fail": 0}
    assert report["vision_faults"] >= 1


def test_vision_monitor_only_does_not_abort():
    from tipseq_plr.steps.vision import CHECK_NOT_OVERDRIED

    cfg = _cfg(
        num_samples=8,
        vision_enabled=True,
        vision_abort_on_fault=False,
        vision_fault_at=(CHECK_NOT_OVERDRIED,),
    )
    report = asyncio.run(DnaLibraryUmi(cfg).run())
    assert report["status"] == "complete"
    assert report["vision_faults"] >= 1
    assert sum(report["counts"].values()) == 8
