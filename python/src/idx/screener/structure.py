"""Structure features and dynamic target / risk level selection.

Uses only OHLC history available at as-of. Never fabricates fixed ±% TP/CL.
Qualified setups require RR >= MIN_RR (default 1:2).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from idx.screener.contract import MIN_RR, SETUP_NOT_QUALIFIED, empty_levels


def idx_tick_size(price: float) -> float:
    if price < 200:
        return 1.0
    if price < 500:
        return 2.0
    if price < 2000:
        return 5.0
    if price < 5000:
        return 10.0
    return 25.0


def round_tick(price: float | None) -> float | None:
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(p) or p <= 0:
        return None
    t = idx_tick_size(p)
    return round(p / t) * t


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    return pd.concat(
        [
            (high - low).abs(),
            (high - prev).abs(),
            (low - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)


def enrich_structure(df: pd.DataFrame) -> pd.DataFrame:
    """Add structure columns using only past/current bars (causal rolling).

    Rolling highs/lows use closed='left' equivalents via shift(1) so the
    current bar's high/low are not used as resistance/support for the same bar
    (avoids same-bar lookahead for level selection).
    """
    if df is None or len(df) == 0:
        return pd.DataFrame()

    g = df.copy()
    for col in ("OpenPrice", "High", "Low", "Close", "Volume", "Value", "Previous"):
        if col in g.columns:
            g[col] = pd.to_numeric(g[col], errors="coerce")

    if "Date" in g.columns:
        g["Date"] = pd.to_datetime(g["Date"], errors="coerce")
        g = g.sort_values("Date").reset_index(drop=True)

    # Ensure High/Low exist for downstream historical evaluation.
    if "High" not in g.columns:
        g["High"] = g["Close"] if "Close" in g.columns else np.nan
    if "Low" not in g.columns:
        g["Low"] = g["Close"] if "Close" in g.columns else np.nan

    c = g["Close"]
    h = g["High"]
    lo = g["Low"]
    v = g["Volume"] if "Volume" in g.columns else pd.Series(np.nan, index=g.index)

    tr = _true_range(h, lo, c)
    g["ATR14"] = tr.ewm(span=14, adjust=False, min_periods=14).mean()

    # Prior-session structure (exclude current bar from lookback windows).
    prior_h = h.shift(1)
    prior_l = lo.shift(1)
    prior_c = c.shift(1)

    for n in (5, 10, 20, 50, 100, 200):
        g[f"HIGH_{n}D"] = prior_h.rolling(n, min_periods=max(3, n // 2)).max()
        g[f"LOW_{n}D"] = prior_l.rolling(n, min_periods=max(3, n // 2)).min()

    g["HIGH_52W"] = prior_h.rolling(252, min_periods=60).max()
    g["LOW_52W"] = prior_l.rolling(252, min_periods=60).min()

    # Causal swing: confirmed pivot at t-2 using only bars <= t-1 (no future).
    ph1 = prior_h
    ph2 = prior_h.shift(1)
    ph3 = prior_h.shift(2)
    g["LAST_SWING_HIGH"] = ph2.where((ph2 > ph1) & (ph2 > ph3)).ffill()
    pl1 = prior_l
    pl2 = prior_l.shift(1)
    pl3 = prior_l.shift(2)
    g["LAST_SWING_LOW"] = pl2.where((pl2 < pl1) & (pl2 < pl3)).ffill()

    g["SMA20"] = prior_c.rolling(20, min_periods=10).mean()
    g["SMA50"] = prior_c.rolling(50, min_periods=20).mean()
    g["VOL20"] = v.shift(1).rolling(20, min_periods=10).mean()
    g["RVOL"] = v / g["VOL20"].replace(0, np.nan)

    if "ForeignBuy" in g.columns and "ForeignSell" in g.columns:
        fb = pd.to_numeric(g["ForeignBuy"], errors="coerce").fillna(0)
        fs = pd.to_numeric(g["ForeignSell"], errors="coerce").fillna(0)
        net = fb - fs
        g["FOREIGN_NET"] = net
        g["FOREIGN_NET_5D"] = net.rolling(5, min_periods=3).sum()
    elif "NetForeignFlow" in g.columns:
        net = pd.to_numeric(g["NetForeignFlow"], errors="coerce").fillna(0)
        g["FOREIGN_NET"] = net
        g["FOREIGN_NET_5D"] = net.rolling(5, min_periods=3).sum()
    else:
        g["FOREIGN_NET"] = np.nan
        g["FOREIGN_NET_5D"] = np.nan

    rng = (h - lo).replace(0, np.nan)
    g["CLOSE_LOC"] = (c - lo) / rng

    return g


def _candidate_targets(row: pd.Series, entry: float) -> list[tuple[float, str]]:
    """Collect resistance levels strictly above entry from available structure."""
    keys = [
        ("LAST_SWING_HIGH", "swing_high"),
        ("HIGH_5D", "5D_high"),
        ("HIGH_10D", "10D_high"),
        ("HIGH_20D", "20D_high"),
        ("HIGH_50D", "50D_high"),
        ("HIGH_100D", "100D_high"),
        ("HIGH_200D", "200D_high"),
        ("HIGH_52W", "52W_high"),
    ]
    atr = float(row["ATR14"]) if "ATR14" in row.index and pd.notna(row["ATR14"]) else None
    candidates: list[tuple[float, str]] = []
    seen: set[float] = set()

    for key, label in keys:
        if key not in row.index or pd.isna(row[key]):
            continue
        level = float(row[key])
        if not np.isfinite(level) or level <= entry:
            continue
        rounded = round_tick(level)
        if rounded is None or rounded <= entry:
            continue
        if rounded in seen:
            continue
        seen.add(rounded)
        candidates.append((rounded, label))

    # ATR extensions only as additional structure-derived options (not fixed %).
    if atr is not None and atr > 0:
        for mult, label in ((1.5, "ATR_1.5"), (2.5, "ATR_2.5"), (3.5, "ATR_3.5")):
            ext = round_tick(entry + mult * atr)
            if ext is None or ext <= entry or ext in seen:
                continue
            seen.add(ext)
            candidates.append((ext, label))

    candidates.sort(key=lambda x: x[0])
    return candidates


def _candidate_stops(row: pd.Series, entry: float) -> list[tuple[float, str]]:
    """Collect invalidation levels strictly below entry from available structure."""
    keys = [
        ("LAST_SWING_LOW", "swing_low"),
        ("LOW_5D", "5D_low"),
        ("LOW_10D", "10D_low"),
        ("LOW_20D", "20D_low"),
        ("LOW_50D", "50D_low"),
        ("LOW_52W", "52W_low"),
    ]
    atr = float(row["ATR14"]) if "ATR14" in row.index and pd.notna(row["ATR14"]) else None
    candidates: list[tuple[float, str]] = []
    seen: set[float] = set()

    for key, label in keys:
        if key not in row.index or pd.isna(row[key]):
            continue
        level = float(row[key])
        if not np.isfinite(level) or level >= entry:
            continue
        rounded = round_tick(level)
        if rounded is None or rounded >= entry:
            continue
        if rounded in seen:
            continue
        seen.add(rounded)
        candidates.append((rounded, label))

    if atr is not None and atr > 0:
        for mult, label in ((0.75, "ATR_0.75"), (1.25, "ATR_1.25"), (1.75, "ATR_1.75")):
            ext = round_tick(entry - mult * atr)
            if ext is None or ext >= entry or ext in seen:
                continue
            seen.add(ext)
            candidates.append((ext, label))

    # Prefer tighter (higher) stops first for CL1, then deeper.
    candidates.sort(key=lambda x: -x[0])
    return candidates


def reward_risk(entry: float, target: float, stop: float) -> float | None:
    risk = entry - stop
    reward = target - entry
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def select_dynamic_levels(
    row: pd.Series,
    *,
    min_rr: float = MIN_RR,
    min_opportunity_pct: float | None = None,
    entry: float | None = None,
) -> dict[str, Any]:
    """Pick up to 3 TP/CL pairs from structure. Unqualified → NOT_QUALIFIED nulls.

    Does NOT invent TP2/TP3 when only one qualified target exists.
    """
    result = empty_levels()
    result["qualified"] = False
    result["setup_status"] = SETUP_NOT_QUALIFIED

    close = float(row["Close"]) if "Close" in row.index and pd.notna(row["Close"]) else None
    if close is None or close <= 0:
        return result

    entry_px = round_tick(entry if entry is not None else close)
    if entry_px is None or entry_px <= 0:
        return result

    result["entry_zone"] = entry_px
    result["entry_source"] = "last_close" if entry is None else "provided_entry"

    targets = _candidate_targets(row, entry_px)
    stops = _candidate_stops(row, entry_px)
    if not targets or not stops:
        return result

    # Primary stop = nearest structural invalidation below entry.
    cl1, cl1_src = stops[0]
    risk = entry_px - cl1
    if risk <= 0:
        return result

    # Filter targets by min opportunity (Close Pressure product floor) and RR.
    floor_pct = min_opportunity_pct
    qualified_tps: list[tuple[float, str, float]] = []
    for tp, src in targets:
        opp_pct = (tp - entry_px) / entry_px * 100.0
        if floor_pct is not None and opp_pct < floor_pct:
            continue
        rr = reward_risk(entry_px, tp, cl1)
        if rr is None or rr < min_rr:
            continue
        qualified_tps.append((tp, src, rr))

    if not qualified_tps:
        return result

    # Assign TP1..TP3 only from truly qualified levels (no fabrication).
    for i, (tp, src, rr) in enumerate(qualified_tps[:3], start=1):
        result[f"tp{i}"] = tp
        result[f"tp{i}_source"] = src
        result[f"rr{i}"] = round(rr, 3)

    result["cl1"] = cl1
    result["cl1_source"] = cl1_src

    # Optional deeper stops (still structural) — never fixed %.
    deeper = [s for s in stops[1:] if s[0] < cl1]
    if deeper:
        result["cl2"] = deeper[0][0]
        result["cl2_source"] = deeper[0][1]
    if len(deeper) > 1:
        result["cl3"] = deeper[1][0]
        result["cl3_source"] = deeper[1][1]

    result["qualified"] = True
    result["setup_status"] = "QUALIFIED"
    return result


def classify_lifecycle(row: pd.Series) -> str:
    """Dormant → Active progression from available daily features."""
    if "Close" not in row.index or pd.isna(row.get("Close")):
        return "UNAVAILABLE"

    rvol = float(row["RVOL"]) if "RVOL" in row.index and pd.notna(row["RVOL"]) else None
    close_loc = (
        float(row["CLOSE_LOC"]) if "CLOSE_LOC" in row.index and pd.notna(row["CLOSE_LOC"]) else None
    )
    high_20 = (
        float(row["HIGH_20D"]) if "HIGH_20D" in row.index and pd.notna(row["HIGH_20D"]) else None
    )
    low_20 = float(row["LOW_20D"]) if "LOW_20D" in row.index and pd.notna(row["LOW_20D"]) else None
    close = float(row["Close"])
    foreign_5 = (
        float(row["FOREIGN_NET_5D"])
        if "FOREIGN_NET_5D" in row.index and pd.notna(row["FOREIGN_NET_5D"])
        else None
    )

    if rvol is None:
        return "UNKNOWN"

    range_pct = None
    if high_20 is not None and low_20 is not None and low_20 > 0:
        range_pct = (high_20 - low_20) / low_20 * 100.0

    breakout = high_20 is not None and close > high_20
    near_high = high_20 is not None and close >= high_20 * 0.98

    if breakout and rvol >= 1.5:
        return "BREAKOUT" if rvol < 2.5 else "EXPANSION"

    if rvol < 0.7 and (range_pct is None or range_pct < 12):
        return "DORMANT"

    if 0.7 <= rvol < 1.2 and (range_pct is None or range_pct < 15):
        return "EARLY_ACTIVITY"

    foreign_acc = foreign_5 is not None and foreign_5 > 0
    tight = range_pct is not None and range_pct < 10
    if (
        (1.0 <= rvol < 1.8)
        and (tight or (close_loc is not None and close_loc >= 0.55))
        and (foreign_acc or close_loc is not None)
    ):
        return "ACCUMULATION"

    if rvol >= 1.2 and (near_high or (close_loc is not None and close_loc >= 0.65)):
        return "ACTIVE"

    if rvol >= 1.0:
        return "EARLY_ACTIVITY"

    return "DORMANT"


def detect_swing_setup(row: pd.Series) -> str | None:
    """Separate swing setup labels from available daily structure (not CP relabel)."""
    if "Close" not in row.index or pd.isna(row["Close"]):
        return None

    close = float(row["Close"])
    rvol = float(row["RVOL"]) if "RVOL" in row.index and pd.notna(row["RVOL"]) else None
    close_loc = (
        float(row["CLOSE_LOC"]) if "CLOSE_LOC" in row.index and pd.notna(row["CLOSE_LOC"]) else None
    )
    sma20 = float(row["SMA20"]) if "SMA20" in row.index and pd.notna(row["SMA20"]) else None
    sma50 = float(row["SMA50"]) if "SMA50" in row.index and pd.notna(row["SMA50"]) else None
    high_20 = (
        float(row["HIGH_20D"]) if "HIGH_20D" in row.index and pd.notna(row["HIGH_20D"]) else None
    )
    low_20 = float(row["LOW_20D"]) if "LOW_20D" in row.index and pd.notna(row["LOW_20D"]) else None
    foreign_5 = (
        float(row["FOREIGN_NET_5D"])
        if "FOREIGN_NET_5D" in row.index and pd.notna(row["FOREIGN_NET_5D"])
        else None
    )
    atr = float(row["ATR14"]) if "ATR14" in row.index and pd.notna(row["ATR14"]) else None

    uptrend = sma20 is not None and sma50 is not None and close > sma20 > sma50
    downtrend = sma20 is not None and sma50 is not None and close < sma20 < sma50

    if high_20 is not None and close > high_20 and rvol is not None and rvol >= 1.3:
        return "breakout"

    if uptrend and low_20 is not None and atr is not None and atr > 0:
        dist = (close - low_20) / atr
        if (
            dist <= 6
            and rvol is not None
            and rvol >= 0.8
            and close_loc is not None
            and close_loc >= 0.45
        ):
            return "pullback"

    if uptrend and rvol is not None and rvol >= 1.3 and close_loc is not None and close_loc >= 0.65:
        return "continuation"

    if (
        foreign_5 is not None
        and foreign_5 > 0
        and rvol is not None
        and rvol >= 1.2
        and (uptrend or (close_loc is not None and close_loc >= 0.55))
    ):
        return "foreign_accumulation"

    if (
        low_20 is not None
        and atr is not None
        and atr > 0
        and (close - low_20) / atr <= 3
        and close_loc is not None
        and close_loc >= 0.55
        and rvol is not None
        and rvol >= 1.0
    ):
        return "support_bounce"

    if (
        downtrend
        and close_loc is not None
        and close_loc >= 0.6
        and rvol is not None
        and rvol >= 1.2
    ):
        return "reversal"

    if (
        rvol is not None
        and rvol >= 1.5
        and classify_lifecycle(row) in ("ACCUMULATION", "EARLY_ACTIVITY")
    ):
        return "accumulation"

    if uptrend and sma20 is not None:
        return "structure"

    return None


def close_pressure_proxy_score(row: pd.Series) -> tuple[float | None, str | None, list[str]]:
    """EOD proxy pressure score — NOT true trade-side dominance.

    Returns (score_0_100, pressure_label, why_parts).
    """
    why: list[str] = []
    score = 0.0
    parts = 0

    close_loc = (
        float(row["CLOSE_LOC"]) if "CLOSE_LOC" in row.index and pd.notna(row["CLOSE_LOC"]) else None
    )
    rvol = float(row["RVOL"]) if "RVOL" in row.index and pd.notna(row["RVOL"]) else None
    foreign_5 = (
        float(row["FOREIGN_NET_5D"])
        if "FOREIGN_NET_5D" in row.index and pd.notna(row["FOREIGN_NET_5D"])
        else None
    )
    high_5 = float(row["HIGH_5D"]) if "HIGH_5D" in row.index and pd.notna(row["HIGH_5D"]) else None
    close = float(row["Close"]) if "Close" in row.index and pd.notna(row["Close"]) else None

    if close_loc is not None:
        parts += 1
        loc_score = max(0.0, min(100.0, close_loc * 100.0))
        score += loc_score
        if close_loc >= 0.7:
            why.append(f"Close in upper range ({close_loc:.2f}) — EOD proxy only")
        else:
            why.append(f"Close location {close_loc:.2f} (EOD proxy, not tape)")

    if rvol is not None:
        parts += 1
        vol_score = max(0.0, min(100.0, (rvol / 2.0) * 100.0))
        score += vol_score
        if rvol >= 1.3:
            why.append(f"Relative volume {rvol:.2f}x")

    if foreign_5 is not None and close is not None:
        parts += 1
        # Sign-only contribution; magnitude not fabricated into fake dominance.
        fscore = 70.0 if foreign_5 > 0 else (30.0 if foreign_5 < 0 else 50.0)
        score += fscore
        why.append(
            "Foreign net 5D positive (aggregate flow, not smart-money attribution)"
            if foreign_5 > 0
            else "Foreign net 5D not supportive"
        )

    if high_5 is not None and close is not None and high_5 > 0:
        parts += 1
        near = close / high_5
        score += max(0.0, min(100.0, (near - 0.9) / 0.1 * 100.0)) if near >= 0.9 else 20.0
        if near >= 0.98:
            why.append("Near prior 5D high (structure)")

    if parts == 0:
        return None, None, ["Insufficient daily features for pressure proxy"]

    avg = score / parts
    if avg >= 70:
        label = "PRESSURE_BUILDING"
    elif avg >= 55:
        label = "WATCH"
    else:
        label = "WEAK"
    why.append("No intraday trade-side / order-book tape — EOD snapshot quality")
    return round(avg, 1), label, why
