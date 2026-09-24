"""Trades whose hold spans a price-distorting CA are excluded (not adjusted away)."""

from __future__ import annotations

import pandas as pd

from idx.backtest import run_backtest


def _universe(*, split_on: str | None = None) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=12)
    rows = []
    for i, d in enumerate(dates):
        iso = d.strftime("%Y-%m-%d")
        split = split_on == iso
        close = 10.0 if split or (split_on and iso > split_on) else 100.0
        prev = 10.0 if split else close
        if i and not split:
            prior = 10.0 if (split_on and dates[i - 1].strftime("%Y-%m-%d") >= split_on) else 100.0
            prev = prior
        for code, c, p, fb, fs in (
            ("AAA", close, prev, 2_000_000.0, 200_000.0),
            ("BBB", 200.0, 200.0 if i == 0 else 200.0, 100_000.0, 2_000_000.0),
        ):
            if code == "BBB":
                c, p = 200.0 + i, 200.0 + max(i - 1, 0)
            rows.append(
                {
                    "Date": iso,
                    "StockCode": code,
                    "OpenPrice": c,
                    "High": c + 1,
                    "Low": c - 1,
                    "Close": c,
                    "Previous": p,
                    "Volume": 1_000_000,
                    "Value": 5e9,
                    "ForeignBuy": fb,
                    "ForeignSell": fs,
                    "TradebleShares": 100_000_000,
                }
            )
    return pd.DataFrame(rows)


_RATIOS = pd.DataFrame([{"code": "AAA", "fsDate": "2025-06-30", "roe": 20.0}])


def _run(**kwargs):
    return run_backtest(
        strategy="foreign_flow",
        holding_days=3,
        top_n=1,
        min_turnover_rp=1e8,
        stock_df=_universe(**{k: kwargs.pop(k) for k in ("split_on",) if k in kwargs}),
        ratios_df=_RATIOS,
        **kwargs,
    )


def test_split_during_hold_is_excluded_from_ledger():
    split_on = pd.bdate_range("2026-01-05", periods=12)[4].strftime("%Y-%m-%d")
    actions = pd.DataFrame(
        [
            {
                "KodeEmiten": "AAA",
                "TanggalPencatatan": split_on,
                "caType": "stockSplit",
            }
        ]
    )
    metrics, trades = _run(split_on=split_on, actions_df=actions)
    assert metrics["exclude_ca_events"] is True
    assert metrics["ca_event_trades_excluded"] >= 1
    if len(trades):
        spans = (pd.to_datetime(trades["EntryDate"]) < split_on) & (
            pd.to_datetime(trades["ExitDate"]) >= split_on
        )
        assert not spans.any()


def test_cash_dividend_does_not_exclude():
    event = pd.bdate_range("2026-01-05", periods=12)[4].strftime("%Y-%m-%d")
    actions = pd.DataFrame(
        [{"KodeEmiten": "AAA", "TanggalPencatatan": event, "caType": "dividenTunai"}]
    )
    metrics, trades = _run(actions_df=actions)
    assert metrics["ca_event_trades_excluded"] == 0
    assert len(trades) > 0


def test_exclusion_can_be_disabled():
    split_on = pd.bdate_range("2026-01-05", periods=12)[4].strftime("%Y-%m-%d")
    actions = pd.DataFrame(
        [{"KodeEmiten": "AAA", "TanggalPencatatan": split_on, "caType": "stockSplit"}]
    )
    on, _ = _run(split_on=split_on, actions_df=actions, exclude_ca_events=True)
    off, trades_off = _run(split_on=split_on, actions_df=actions, exclude_ca_events=False)
    assert on["ca_event_trades_excluded"] >= 1
    assert off["ca_event_trades_excluded"] == 0
    assert off["exclude_ca_events"] is False
    assert len(trades_off) >= on["ca_event_trades_excluded"]


def test_exchange_reference_split_is_excluded_without_ca_table():
    split_on = pd.bdate_range("2026-01-05", periods=12)[4].strftime("%Y-%m-%d")
    metrics, trades = _run(split_on=split_on, actions_df=None)
    assert metrics["ca_event_trades_excluded"] >= 1
    if len(trades):
        spans = (pd.to_datetime(trades["EntryDate"]) < split_on) & (
            pd.to_datetime(trades["ExitDate"]) >= split_on
        )
        assert not spans.any()
