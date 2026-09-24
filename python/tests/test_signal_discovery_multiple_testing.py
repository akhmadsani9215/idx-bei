"""Cluster 8 — PSR / Deflated Sharpe / Benjamini–Hochberg."""

from __future__ import annotations

import random

import pytest

from idx.signal_discovery.multiple_testing import (
    MIN_PERIODS,
    benjamini_hochberg,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    mean_return_pvalue,
    probabilistic_sharpe_ratio,
    return_moments,
)


def test_psr_matches_closed_form():
    # z = 0.1 * sqrt(99) / sqrt(1 + 0.25 * 2 * 0.01)
    assert probabilistic_sharpe_ratio(0.1, 0.0, 100, 0.0, 3.0) == pytest.approx(0.8395, abs=1e-3)
    assert probabilistic_sharpe_ratio(0.0, 0.0, 100, 0.0, 3.0) == pytest.approx(0.5)
    assert probabilistic_sharpe_ratio(0.1, 0.0, 1, 0.0, 3.0) is None


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1, 1.0) == 0.0
    assert expected_max_sharpe(100, 1.0) == pytest.approx(2.53, abs=0.01)
    assert expected_max_sharpe(1000, 1.0) > expected_max_sharpe(100, 1.0)
    assert expected_max_sharpe(100, 0.0) == 0.0


def test_moments_of_symmetric_series():
    m = return_moments([0.01, -0.01] * 20)
    assert m["periods"] == 40
    assert m["mean"] == pytest.approx(0.0)
    assert m["skew"] == pytest.approx(0.0)
    assert m["kurtosis"] == pytest.approx(1.0)


def test_dsr_penalises_many_trials():
    rng = random.Random(7)
    rets = [0.004 + rng.gauss(0, 0.02) for _ in range(120)]
    trial_sharpes = [rng.gauss(0, 0.1) for _ in range(50)]
    few = deflated_sharpe_ratio(rets, trial_sharpes=trial_sharpes[:2], n_trials=2)
    many = deflated_sharpe_ratio(rets, trial_sharpes=trial_sharpes, n_trials=50)
    assert few["status"] in ("PASS", "FAIL")
    assert many["dsr"] < few["dsr"]
    assert many["expected_max_sharpe"] > few["expected_max_sharpe"]


def test_dsr_insufficient_periods():
    out = deflated_sharpe_ratio([0.01] * (MIN_PERIODS - 1), trial_sharpes=[0.1, 0.2], n_trials=2)
    assert out["status"] == "INSUFFICIENT_DATA"
    assert out["dsr"] is None


def test_mean_pvalue_and_bh():
    assert mean_return_pvalue([0.01] * 5) is None
    rng = random.Random(3)
    strong = [0.01 + rng.gauss(0, 0.01) for _ in range(60)]
    noise = [rng.gauss(0, 0.01) for _ in range(60)]
    pvals = {
        "strong": mean_return_pvalue(strong),
        "noise": mean_return_pvalue(noise),
        "short": None,
    }
    assert pvals["strong"] < 0.001
    out = benjamini_hochberg(pvals, alpha=0.1)
    assert out["decisions"]["strong"] == "DISCOVERY"
    assert out["decisions"]["short"] == "UNTESTABLE"
    assert out["tested"] == 2


def test_bh_step_up_rule():
    out = benjamini_hochberg({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5}, alpha=0.05)
    # ranks: a .01<=.0125, c .03<=.025? no, b .04<=.0375? no → only a
    assert out["discoveries"] == ["a"]
    out = benjamini_hochberg({"a": 0.01, "b": 0.02, "c": 0.03}, alpha=0.05)
    assert out["discoveries"] == ["a", "b", "c"]
