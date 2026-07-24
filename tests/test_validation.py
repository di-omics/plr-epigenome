"""Tests for the liquid-test validation framework (Rhodamine B criteria)."""

from tipseq_plr.validation import (
    PROTOCOL_STATUS,
    Reading,
    RhodamineCriteria,
    Standard,
    ValidationTier,
    evaluate,
)


def _std():
    # linear Rhodamine curve: RFU = 950*vol + 50, covering sub-uL to 40 uL
    return [Standard(v, 950 * v + 50) for v in (0.5, 1, 2, 5, 10, 20, 40)]


def _rfu(v):
    return 950 * v + 50


def test_all_protocols_start_untested():
    assert set(PROTOCOL_STATUS) == {"tipseq", "cut_and_tag", "normalization", "hydrop_atac",
                                    "dna_library_umi"}
    assert all(s["tier"] == ValidationTier.UNTESTED for s in PROTOCOL_STATUS.values())
    assert all(s["liquid_dataset"] is None for s in PROTOCOL_STATUS.values())


def test_clean_run_is_liquid_tested():
    reads = []
    for t, deltas in ((10, (0.05, -0.03, 0.02, -0.01)), (20, (0.1, -0.1, 0.05, -0.05))):
        for i, d in enumerate(deltas):
            reads.append(Reading(f"{t}_{i}", t, _rfu(t + d)))
    r = evaluate(_std(), reads)
    assert r["liquid_tested"] is True
    assert r["tier"] == "liquid_tested"
    assert r["standard_curve"]["r2"] >= 0.995


def test_high_cv_fails():
    reads = [Reading("A1", 10, _rfu(12)), Reading("A2", 10, _rfu(8)), Reading("A3", 10, _rfu(11.5))]
    r = evaluate(_std(), reads)
    assert r["liquid_tested"] is False
    assert any("CV" in reason for reason in r["reasons"])


def test_too_few_replicates_fails():
    r = evaluate(_std(), [Reading("A1", 10, _rfu(10)), Reading("A2", 10, _rfu(10))])
    assert r["liquid_tested"] is False
    assert any("replicate" in reason for reason in r["reasons"])


def test_out_of_range_reading_fails():
    r = evaluate(_std(), [Reading(f"A{i}", 10, 70000) for i in range(3)])
    assert r["liquid_tested"] is False
    assert any("range" in reason for reason in r["reasons"])


def test_nonlinear_standard_curve_fails():
    bad = [Standard(2, 100), Standard(5, 100), Standard(10, 9000), Standard(20, 9100)]
    reads = [Reading(f"A{i}", 10, _rfu(10)) for i in range(3)]
    r = evaluate(bad, reads)
    assert r["liquid_tested"] is False
    assert r["standard_curve"]["r2"] < 0.995


def test_looser_tolerance_below_2ul():
    # 1 uL target: 12% accuracy error passes the <2 uL tier (15%) but would fail >=10 uL tier
    crit = RhodamineCriteria()
    reads = [Reading(f"A{i}", 1.0, _rfu(1.12)) for i in range(4)]
    r = evaluate(_std(), reads, crit)
    grp = r["groups"][0]
    assert grp["target_ul"] == 1.0
    assert grp["passed"] is True and grp["accuracy_pct"] <= 15.0
