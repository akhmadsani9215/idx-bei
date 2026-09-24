"""Exchange-reference corporate-action adjustment (causal forward / backward rescale)."""

from __future__ import annotations

import pandas as pd
import pytest

from idx.core.price_adjustment import (
    adjustment_events,
    backward_adjust,
    forward_adjust,
    reference_factors,
)


def _series(closes, previous, dates=None, code="AAA"):
    dates = dates or [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-01-05", periods=len(closes))]
    return pd.DataFrame(
        {
            "Date": dates,
            "StockCode": code,
            "OpenPrice": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Previous": previous,
            "Volume": [1000.0] * len(closes),
        }
    )


def test_split_is_detected_and_forward_adjusted_causally():
    # 1:10 split on day 3: reference price 10 vs prior close 100
    df = _series([100.0, 100.0, 10.5, 11.0], [100.0, 100.0, 10.0, 10.5])
    f = reference_factors(df)
    assert list(f) == [1.0, 1.0, 0.1, 1.0]
    adj = forward_adjust(df)
    assert adj["Close"].tolist() == pytest.approx([100.0, 100.0, 105.0, 110.0])
    assert adj["Volume"].tolist() == pytest.approx([1000.0, 1000.0, 100.0, 100.0])
    # causal: pre-split bars untouched by the later event
    assert adj["Close"].iloc[:2].tolist() == [100.0, 100.0]


def test_backward_adjust_keeps_last_bar_raw():
    df = _series([100.0, 100.0, 10.5, 11.0], [100.0, 100.0, 10.0, 10.5])
    adj = backward_adjust(df)
    assert adj["Close"].tolist() == pytest.approx([10.0, 10.0, 10.5, 11.0])


def test_no_adjustment_when_previous_equals_prior_close_or_tick_noise():
    df = _series([100.0, 101.0, 102.0], [100.0, 100.0, 101.05])  # 0.05% rounding noise
    assert list(reference_factors(df)) == [1.0, 1.0, 1.0]


def test_gap_and_missing_values_do_not_create_factors():
    dates = ["2026-01-05", "2026-01-06", "2026-03-20"]
    df = _series([100.0, 100.0, 50.0], [100.0, 100.0, 40.0], dates=dates)
    assert list(reference_factors(df)) == [1.0, 1.0, 1.0]
    df2 = _series([100.0, float("nan"), 50.0], [100.0, 100.0, 45.0])
    assert list(reference_factors(df2)) == [1.0, 1.0, 1.0]


def test_multi_ticker_isolation_and_events():
    a = _series([100.0, 10.0], [100.0, 10.0], code="AAA")
    b = _series([50.0, 51.0], [50.0, 50.0], code="BBB")
    df = pd.concat([b, a], ignore_index=True)
    ev = adjustment_events(df)
    assert ev["StockCode"].tolist() == ["AAA"]
    assert ev["factor"].iloc[0] == pytest.approx(0.1)


def test_empty_and_missing_columns():
    assert reference_factors(pd.DataFrame()).empty
    df = _series([1.0, 2.0], [1.0, 1.0]).drop(columns=["Previous"])
    assert list(reference_factors(df)) == [1.0, 1.0]
