"""Screener historical stats: first-touch TP vs CL, complete horizons, no gap crossing."""

from __future__ import annotations

import numpy as np
import pandas as pd

from idx.screener.contract import PRODUCTION_ELIGIBILITY_STATUS, base_result
from idx.screener.historical import _first_touch, _gap_free, historical_stats_for_frame


def test_stop_touched_before_target_counts_as_cl():
    highs = np.array([100, 101, 102, 112, 115], dtype=float)
    lows = np.array([99, 94, 100, 105, 110], dtype=float)  # bar 1 breaks CL=95 first
    assert _first_touch(highs, lows, tp=110.0, cl=95.0, start_i=0, horizon=4) == ("CL", 1)
    assert _first_touch(highs, lows, tp=110.0, cl=90.0, start_i=0, horizon=4) == ("TP", 3)


def test_same_bar_tp_and_cl_is_conservative():
    highs = np.array([100, 120], dtype=float)
    lows = np.array([100, 80], dtype=float)
    assert _first_touch(highs, lows, tp=110.0, cl=90.0, start_i=0, horizon=1) == ("CL", 1)


def test_gap_free_window():
    d = pd.to_datetime(["2025-03-14", "2025-03-17", "2025-09-01", "2025-09-02"]).to_numpy()
    assert _gap_free(d, 0, 1)
    assert not _gap_free(d, 0, 2)
    assert _gap_free(d, 2, 1)


def _frame(n: int, gap_after: int | None = None) -> pd.DataFrame:
    dates = list(pd.bdate_range("2025-01-02", periods=n))
    if gap_after is not None:
        dates = dates[:gap_after] + [d + pd.Timedelta(days=150) for d in dates[gap_after:]]
    rng = np.random.default_rng(1)
    close = 1000 + np.cumsum(rng.normal(0, 15, n))
    return pd.DataFrame(
        {
            "Date": dates,
            "OpenPrice": close,
            "High": close + 20,
            "Low": close - 20,
            "Close": close,
            "Volume": 1_000_000,
            "Value": 1e9,
        }
    )


def test_incomplete_and_gap_windows_are_excluded():
    plain = historical_stats_for_frame(_frame(200), horizon=10)
    gapped = historical_stats_for_frame(_frame(200, gap_after=100), horizon=10)
    assert plain["skipped_data_gap"] == 0
    # every qualified signal whose 10-bar window spans the 150-day gap is dropped
    assert gapped["sample_size"] <= plain["sample_size"]
    assert "FIRST_TOUCH" in plain["outcome_basis"]
    if plain["sample_size"]:
        tp, cl = plain["historical_tp_probability"], plain["historical_cl_probability"]
        assert tp is not None and cl is not None and tp + cl <= 100.0


def test_screener_rows_are_never_production_eligible():
    row = base_result(ticker="bbca")
    assert row["production_eligibility"] == PRODUCTION_ELIGIBILITY_STATUS == "NOT_VALIDATED"
