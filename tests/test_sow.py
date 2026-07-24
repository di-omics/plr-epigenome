"""Tests for the Statement-of-Work compiler (no hardware)."""

import asyncio

from tipseq_plr.sow import SoW, compile_run, route


def test_routes_by_intent():
    cases = {
        "CUT&Tag for H3K4me3, 48 samples": "cut_and_tag",
        "single-cell ATAC via HyDrop droplet gen": "hydrop_atac",
        "normalize a 96-well plate to equimolar with dsDNA fluorescence": "normalization",
        "TIP-seq epigenomic profiling, 96 samples": "tipseq",
    }
    for text, expected in cases.items():
        assert route(SoW.from_text(text)) == expected


def test_default_route_is_tipseq():
    assert route(SoW.from_text("map chromatin protein binding in single cells")) == "tipseq"


def test_parses_samples_and_targets_and_dedupes_substrings():
    sow = SoW.from_text("96-well run for H3K27me3, CTCF, RNAPII-Ser2P and IgG")
    assert sow.samples == 96
    assert "RNAPII-Ser2P" in sow.targets and "RNAPII" not in sow.targets   # substring dropped
    assert "CTCF" in sow.targets and "IgG" in sow.targets


def test_sci_detection_and_executable_plan():
    run = compile_run(SoW.from_text("sciTIP-seq combinatorial single-cell indexing, 96 samples"))
    plan = run.plan()
    assert plan["routed_to"] == "tipseq"
    assert plan["method"] == "scitip_seq"
    assert plan["executable"] is True
    assert plan["validation_tier"] == "untested"     # nothing trusted before a liquid test
    assert plan["cli"].startswith("python -m tipseq_plr.protocols.tipseq.run")


def test_missing_sample_count_defaults_with_note():
    run = compile_run(SoW.from_text("CUT&Tag for H3K27me3"))
    assert run.config.num_samples == 96
    assert any("defaulted" in n for n in run.notes)


def test_compiled_run_actually_executes():
    run = compile_run(SoW.from_text("CUT&Tag H3K27me3, 8 samples"))
    report = asyncio.run(run.run())
    assert report["method"] == "cut_and_tag"
    assert sum(report["counts"].values()) == 8


def test_from_dict():
    sow = SoW.from_dict({"title": "HyDrop scATAC", "samples": 8})
    assert compile_run(sow).protocol == "hydrop_atac"
