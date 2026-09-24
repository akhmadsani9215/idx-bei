"""Corporate-action price adjustment from the exchange reference price.

IDX ``stock_summary.Previous`` equals the prior session Close except on ex-dates,
where the exchange publishes the theoretical reference price (splits, reverse
splits, bonus shares, rights/TERP). Verified on local data 2025-01→2026-09:
289,336 consecutive rows, 34 deviations > 0.1%, all corporate actions.

Per-session factor ``f_t = Previous_t / Close_{t-1}`` (1.0 when |f-1| <= tolerance,
the prior bar is missing, or the two bars are split by a data gap).

* ``forward_adjust`` — causal: divides prices by the cumulative factor up to t
  (uses only events on or before t). For backtests / features.
* ``backward_adjust`` — rescales history into the latest share basis so the last
  bar stays the raw, tradable price. For descriptive per-ticker stats only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REFERENCE_TOLERANCE = 0.001
MAX_ADJACENT_GAP_DAYS = 14
PRICE_COLUMNS = ("OpenPrice", "High", "Low", "Close", "Previous", "VWAP")
PRICE_BASIS = "EXCHANGE_REFERENCE_ADJUSTED"

# corporate_actions.caType values that change share count / price basis.
PRICE_DISTORTING_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "stockSplit",
        "reverseStock",
        "sahamBonus",
        "dividenSaham",
        "hmetd",
        "kurangModal",
        "gabungUsaha",
    }
)
# Full delisting types; ``partialDelisting`` is a share-count event, not a delisting.
DELISTING_ACTION_TYPES: frozenset[str] = frozenset({"delisting", "forcedDelisting"})


def reference_factors(df: pd.DataFrame) -> pd.Series:
    """Per-row adjustment factor (index-aligned with ``df``)."""
    ones = pd.Series(1.0, index=df.index)
    if df.empty or not {"Date", "StockCode", "Close", "Previous"} <= set(df.columns):
        return ones
    order = df.sort_values(["StockCode", "Date"]).index
    s = df.loc[order, ["Date", "StockCode", "Close", "Previous"]]
    dates = pd.to_datetime(s["Date"], errors="coerce")
    grp = s["StockCode"]
    prior_close = pd.to_numeric(s["Close"], errors="coerce").groupby(grp).shift(1)
    prior_date = dates.groupby(grp).shift(1)
    prev = pd.to_numeric(s["Previous"], errors="coerce")
    f = prev / prior_close
    valid = (
        f.notna()
        & np.isfinite(f)
        & (f > 0)
        & ((dates - prior_date).dt.days <= MAX_ADJACENT_GAP_DAYS)
        & ((f - 1.0).abs() > REFERENCE_TOLERANCE)
    )
    out = pd.Series(1.0, index=order)
    out[valid] = f[valid]
    return out.reindex(df.index).fillna(1.0)


def _cumulative(df: pd.DataFrame, factors: pd.Series) -> pd.Series:
    order = df.sort_values(["StockCode", "Date"]).index
    return factors.loc[order].groupby(df.loc[order, "StockCode"]).cumprod().reindex(df.index)


def _apply(df: pd.DataFrame, scale: pd.Series) -> pd.DataFrame:
    out = df.copy()
    for col in PRICE_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce") * scale
    if "Volume" in out.columns:
        out["Volume"] = pd.to_numeric(out["Volume"], errors="coerce") / scale
    return out


def forward_adjust(df: pd.DataFrame) -> pd.DataFrame:
    """Causal adjustment: prices in the share basis of each ticker's first bar."""
    factors = reference_factors(df)
    cum = _cumulative(df, factors)
    out = _apply(df, 1.0 / cum)
    out["AdjFactor"] = factors
    return out


def backward_adjust(df: pd.DataFrame) -> pd.DataFrame:
    """History rescaled to the latest share basis (last bar = raw price)."""
    factors = reference_factors(df)
    cum = _cumulative(df, factors)
    last = cum.groupby(df["StockCode"]).transform("last")
    out = _apply(df, last / cum)
    out["AdjFactor"] = factors
    return out


def adjustment_events(df: pd.DataFrame) -> pd.DataFrame:
    """Rows where a reference-price adjustment occurred (for audit/reporting)."""
    factors = reference_factors(df)
    mask = factors != 1.0
    cols = [c for c in ("Date", "StockCode", "Previous", "Close") if c in df.columns]
    return df.loc[mask, cols].assign(factor=factors[mask])
