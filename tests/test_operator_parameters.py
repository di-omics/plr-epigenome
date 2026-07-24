"""Fail-closed tests for operator-supplied Hamilton assay parameters."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "hamilton-star" / "operator_parameters.py"
SCHEMA_PATH = Path(__file__).parents[1] / "hamilton-star" / "method-parameters.schema.json"


def _module():
    spec = importlib.util.spec_from_file_location("hamilton_operator_parameters", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_is_required_before_assay_values_are_read(monkeypatch):
    module = _module()
    monkeypatch.delenv(module.PROFILE_ENV, raising=False)

    with pytest.raises(module.MethodParameterError, match=module.PROFILE_ENV):
        module.required_positive("wgs.stage_1_volume_ul")


def test_operator_values_are_loaded_by_dotted_path(monkeypatch, tmp_path):
    module = _module()
    profile = tmp_path / "method.json"
    profile.write_text(
        json.dumps({"wgs": {"stage_1_volume_ul": 1.25, "cleanup": {"wait_s": 0}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(module.PROFILE_ENV, str(profile))

    assert module.required_positive("wgs.stage_1_volume_ul") == 1.25
    assert module.required_nonnegative("wgs.cleanup.wait_s") == 0


def test_schema_and_loader_share_pcr_enrichment_key(monkeypatch, tmp_path):
    module = _module()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "pcr_enrichment" in schema["properties"]

    profile = tmp_path / "method.json"
    profile.write_text(
        json.dumps({"pcr_enrichment": {"round_1_transfer_ul": 2.5}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(module.PROFILE_ENV, str(profile))

    assert module.required_positive("pcr_enrichment.round_1_transfer_ul") == 2.5


@pytest.mark.parametrize("bad_value", [0, -1, "1", True, float("nan")])
def test_positive_values_reject_unsafe_inputs(monkeypatch, tmp_path, bad_value):
    module = _module()
    profile = tmp_path / "method.json"
    profile.write_text(
        json.dumps({"wgs": {"stage_1_volume_ul": bad_value}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(module.PROFILE_ENV, str(profile))

    with pytest.raises(module.MethodParameterError):
        module.required_positive("wgs.stage_1_volume_ul")
