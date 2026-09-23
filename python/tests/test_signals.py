"""Tests for idx.signals decision-support screens (pure DataFrame transforms)."""

import pandas as pd
import pytest

from idx.signals import (
    audit_risk_shield,
    dilution_watch,
    foreign_flow_radar,
    pasar_nego_crossing_screen,
    sharia_value_screen,
)


@pytest.fixture
def stock_df():
    return pd.DataFrame(
        {
            "Date": ["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"] * 3,
            "StockCode": ["AAA"] * 4 + ["BBB"] * 4 + ["CCC"] * 4,
            "Close": [100.0] * 8 + [50.0] * 4,
            "Value": [5e9] * 8 + [1e8] * 4,  # CCC is illiquid
            "TradebleShares": [1e9] * 8 + [1e7] * 4,
            "NetForeignFlow": [30e6] * 4 + [-10e6] * 4 + [0.0] * 4,
            "NonRegularValue": [30e9] * 4 + [0.0] * 8,  # AAA has heavy nego crossing
            "NonRegularVolume": [3e8] * 4 + [0.0] * 8,
            "NonRegularFrequency": [10] * 4 + [0] * 8,
        }
    )


def test_pasar_nego_screen_flags_heavy_crossing(stock_df):
    out = pasar_nego_crossing_screen(stock_df, min_nego_val_rp=50e9, min_nego_pct=70.0)
    assert len(out) == 1
    assert out.iloc[0]["StockCode"] == "AAA"
    # Total nego: 4 * 30B = 120B
    assert out.iloc[0]["NegoValRpB"] == pytest.approx(120.0)
    # Total regular: 4 * 5B = 20B -> Share = 120 / (120 + 20) = 85.7%
    assert out.iloc[0]["NegoSharePct"] == pytest.approx(85.7, rel=1e-2)
    assert out.iloc[0]["NegoTrades"] == 40


def test_screens_handle_empty_input():
    empty = pd.DataFrame()
    assert foreign_flow_radar(empty).empty
    assert audit_risk_shield(empty).empty
    assert dilution_watch(empty).empty
    assert sharia_value_screen(empty).empty
    assert pasar_nego_crossing_screen(empty).empty


def test_radar_flags_accumulation_and_distribution(stock_df):
    out = foreign_flow_radar(stock_df, min_abs_pct_float=0.5)
    by_code = out.set_index("StockCode")

    assert set(out["Signal"]) == {"foreign_inflow", "foreign_outflow"}
    # AAA: +120M shares / 1e9 float = 12% -> foreign_inflow
    assert by_code.loc["AAA", "Signal"] == "foreign_inflow"
    assert by_code.loc["AAA", "PctFloat"] == pytest.approx(12.0)
    # BBB: -40M / 1e9 = -4% -> foreign_outflow
    assert by_code.loc["BBB", "Signal"] == "foreign_outflow"
    assert by_code.loc["BBB", "PctFloat"] == pytest.approx(-4.0)
    # Sorted strongest first
    assert out["PctFloat"].is_monotonic_decreasing


def test_radar_filters_illiquid_and_zero_flow(stock_df):
    out = foreign_flow_radar(stock_df, min_turnover_rp=1e9)
    assert "CCC" not in set(out["StockCode"])  # turnover below floor


def test_radar_window_limits_sessions():
    df = pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=10).strftime("%Y-%m-%d"),
            "StockCode": ["AAA"] * 10,
            "Close": [100.0] * 10,
            "Value": [5e9] * 10,
            "TradebleShares": [1e9] * 10,
            "NetForeignFlow": [10e6] * 10,
        }
    )
    out = foreign_flow_radar(df, window_days=3)
    assert out.loc[0, "Sessions"] == 3


def test_audit_shield_flags_only_non_clean_latest_filing():
    ratios = pd.DataFrame(
        {
            "code": ["NEST", "NEST", "AMMN"],
            "stockName": ["A", "A", "C"],
            "fsDate": ["2025-12-31", "2024-12-31", "2025-12-31"],
            "opini": ["WDP", "WTM", "WTM"],
            "roe": [5.0, 4.0, 20.0],
            "per": [8.0, 7.0, 9.0],
        }
    )
    out = audit_risk_shield(ratios)
    # NEST flagged once on its LATEST filing; clean AMMN excluded
    assert list(out["code"]) == ["NEST"]
    assert out.loc[0, "opini"] == "WDP"
    assert str(out.loc[0, "fsDate"])[:10] == "2025-12-31"


def test_dilution_watch_scope_and_lookback():
    actions = pd.DataFrame(
        {
            "KodeEmiten": ["NEW", "OLD", "DIV", "FUT"],
            "TanggalPencatatan": [
                "2026-06-01",
                "2026-01-01",
                "2026-05-20",
                "2027-06-01",
            ],
            "JenisTindakan": [
                "Private Placement",
                "Rights Issue",
                "Dividend",
                "Warrant",
            ],
            "caType": ["PrivatePlacement", "kurangModal", "hmetd", "waran"],
        }
    )
    out = dilution_watch(actions, lookback_days=90, on_date="2026-08-25")
    assert list(out["KodeEmiten"]) == ["NEW"]  # OLD outside window, DIV not dilutive,
    # FUT in the future


def test_sharia_screen_filters_flag_valuation_and_opinion():
    ratios = pd.DataFrame(
        {
            "code": ["GOOD", "NONSHARIA", "EXPENSIVE", "WEAKROE", "RISKY", "STALE"],
            "stockName": ["g", "n", "e", "w", "r", "s"],
            "fsDate": ["2025-12-31"] * 6,
            "sharia": ["S", "-", "S", "S", "S", "S"],
            "per": [8.0, 5.0, 20.0, 5.0, 5.0, 5.0],
            "roe": [30.0, 50.0, 50.0, 5.0, 50.0, 50.0],
            "deRatio": [0.5] * 6,
            "priceBV": [1.0] * 6,
            "opini": ["WTM", "WTM", "WTM", "WTM", "WDP", "TMP"],
        }
    )
    out = sharia_value_screen(ratios)
    assert list(out["code"]) == ["GOOD"]


def test_build_briefing(tmp_path):
    from idx.signals import build_briefing

    res = build_briefing(out_dir=str(tmp_path))
    assert "markdown" in res
    assert "json" in res
    assert "trade_date" in res


def test_composite_alpha_and_tech_indicators(stock_df):
    from idx.signals import composite_alpha_ranking, compute_technical_indicators

    tech = compute_technical_indicators(stock_df)
    assert not tech.empty
    assert "RSI14" in tech.columns
    assert "TrendRegime" in tech.columns

    ratios = pd.DataFrame(
        [{"code": "AAA", "per": "10.0", "roe": "25.0", "opini": "WTM", "fsDate": "2026-06-30"}]
    )
    alpha = composite_alpha_ranking(stock_df, ratios, min_turnover_rp=1e8)
    assert isinstance(alpha, pd.DataFrame)


def test_trend_regime_is_point_in_time_per_row():
    """TrendRegime must reflect each row's own close vs EMAs, not the final bar only."""
    from idx.signals import compute_technical_indicators

    # Construct a clear regime change: early bearish stretch then a strong rally.
    n = 60
    closes = [100.0 - i * 0.5 for i in range(30)] + [85.0 + i * 1.5 for i in range(30)]
    df = pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=n).strftime("%Y-%m-%d"),
            "StockCode": ["AAA"] * n,
            "OpenPrice": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": [1e6] * n,
            "Previous": [closes[0]] + closes[:-1],
        }
    )
    tech = compute_technical_indicators(df)
    # Broadcast bug would assign a single regime to every historical row.
    assert tech["TrendRegime"].nunique() > 1
    assert tech.iloc[25]["TrendRegime"] != tech.iloc[-1]["TrendRegime"]


def test_foreign_flow_close_uses_latest_session_not_row_order():
    from idx.signals import foreign_flow_radar

    # Deliberately reverse chronological row order within the ticker.
    df = pd.DataFrame(
        {
            "Date": ["2026-08-07", "2026-08-06", "2026-08-05", "2026-08-04"],
            "StockCode": ["AAA"] * 4,
            "Close": [140.0, 130.0, 120.0, 110.0],
            "Value": [5e9] * 4,
            "TradebleShares": [1e9] * 4,
            "NetForeignFlow": [10e6] * 4,
        }
    )
    out = foreign_flow_radar(df, window_days=4, min_abs_pct_float=0.0, min_turnover_rp=1e8)
    assert float(out.iloc[0]["Close"]) == 140.0


def test_latest_per_code_respects_as_of_cutoff():
    from idx.signals import _latest_per_code, composite_alpha_ranking

    ratios = pd.DataFrame(
        {
            "code": ["AAA", "AAA"],
            "stockName": ["A", "A"],
            "fsDate": ["2025-06-30", "2026-06-30"],
            "per": [8.0, 50.0],
            "roe": [10.0, 40.0],
            "deRatio": [0.5, 0.5],
            "opini": ["WTM", "WTM"],
        }
    )
    pit = _latest_per_code(ratios, as_of="2025-12-31")
    assert len(pit) == 1
    assert float(pit.iloc[0]["per"]) == 8.0

    # Undated filings must not leak through an as_of cutoff.
    with_undated = pd.concat(
        [
            ratios,
            pd.DataFrame(
                [
                    {
                        "code": "AAA",
                        "stockName": "A",
                        "fsDate": None,
                        "per": 1.0,
                        "roe": 99.0,
                        "deRatio": 0.1,
                        "opini": "WTM",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    pit_undated = _latest_per_code(with_undated, as_of="2025-12-31")
    assert len(pit_undated) == 1
    assert float(pit_undated.iloc[0]["per"]) == 8.0

    stock = pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=5).strftime("%Y-%m-%d"),
            "StockCode": ["AAA"] * 5,
            "Close": [100.0] * 5,
            "Value": [5e9] * 5,
            "TradebleShares": [1e9] * 5,
            "NetForeignFlow": [10e6] * 5,
            "ForeignBuy": [20e6] * 5,
            "ForeignSell": [10e6] * 5,
        }
    )
    alpha_future = composite_alpha_ranking(stock, ratios, min_turnover_rp=1e8, as_of="2026-12-31")
    alpha_past = composite_alpha_ranking(stock, ratios, min_turnover_rp=1e8, as_of="2025-12-31")
    assert not alpha_past.empty
    # Past cutoff must not see the 2026 filing PER=50.
    assert float(alpha_past.iloc[0]["PER"]) == pytest.approx(8.0)
    assert float(alpha_future.iloc[0]["PER"]) == pytest.approx(50.0)
