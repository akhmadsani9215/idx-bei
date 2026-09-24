"""Historical stats for screener setups without contaminating live signals.

Past signal outcomes may use bars AFTER those historical signal dates
(evaluation only). Live level selection must never use future highs/lows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from idx.backtest import MAX_SESSION_GAP_DAYS
from idx.screener.contract import (
    MIN_HISTORICAL_SAMPLE,
    MIN_RR,
    STATUS_INSUFFICIENT_SAMPLE,
    STATUS_UNAVAILABLE,
    empty_historical_stats,
)
from idx.screener.structure import enrich_structure, select_dynamic_levels

OUTCOME_BASIS = (
    "FIRST_TOUCH — TP vs CL on subsequent bars within a complete, gap-free horizon; "
    "same-bar TP+CL counts as CL (conservative)"
)


def _forward_mfe_mae(
    highs: np.ndarray,
    lows: np.ndarray,
    entry: float,
    start_i: int,
    horizon: int,
) -> tuple[float | None, float | None, int | None]:
    """MFE/MAE over subsequent bars only (no same-bar signal contamination)."""
    end = min(len(highs), start_i + 1 + horizon)
    if start_i + 1 >= end or entry <= 0:
        return None, None, None

    window_h = highs[start_i + 1 : end]
    window_l = lows[start_i + 1 : end]
    if len(window_h) == 0:
        return None, None, None

    mfe = float(np.nanmax((window_h / entry - 1.0) * 100.0))
    mae = float(np.nanmin((window_l / entry - 1.0) * 100.0))
    # Days to first touch of +MFE peak (approx): index of max high
    peak_i = int(np.nanargmax(window_h))
    days = peak_i + 1
    return mfe, mae, days


def _first_touch(
    highs: np.ndarray,
    lows: np.ndarray,
    tp: float,
    cl: float | None,
    start_i: int,
    horizon: int,
) -> tuple[str, int | None]:
    """``("TP"|"CL"|"NONE", bars)`` — whichever level is touched first after the signal bar."""
    end = min(len(highs), start_i + 1 + horizon)
    for j in range(start_i + 1, end):
        if cl is not None and lows[j] <= cl:
            return "CL", j - start_i
        if highs[j] >= tp:
            return "TP", j - start_i
    return "NONE", None


def _gap_free(dates: np.ndarray | None, start_i: int, horizon: int) -> bool:
    if dates is None:
        return True
    window = dates[start_i : start_i + horizon + 1]
    if len(window) < 2:
        return True
    steps = np.diff(window).astype("timedelta64[D]").astype(int)
    return bool((steps <= MAX_SESSION_GAP_DAYS).all())


def compute_historical_stats(
    enriched: pd.DataFrame,
    *,
    signal_mask: pd.Series | None = None,
    signal_fn: Callable[[pd.Series], bool] | None = None,
    horizon: int = 10,
    min_rr: float = MIN_RR,
    min_opportunity_pct: float | None = None,
    min_sample: int = MIN_HISTORICAL_SAMPLE,
    # Exclude the final bar from historical sample generation to avoid
    # using the live decision bar as an evaluated trade.
    exclude_last: bool = True,
) -> dict[str, Any]:
    """Replay past bars: PIT levels → forward MFE/MAE/TP-hit.

    Signal bars are identified without future data. Outcomes use only bars
    after each historical signal index.
    """
    out = empty_historical_stats()
    if enriched is None or len(enriched) < 20:
        out["stats_status"] = STATUS_UNAVAILABLE
        out["stats_note"] = "Insufficient history for stats."
        return out

    g = enriched.reset_index(drop=True)
    n = len(g)
    last_i = n - 1 if exclude_last else n
    if last_i < 15:
        out["stats_status"] = STATUS_UNAVAILABLE
        out["stats_note"] = "Insufficient history for stats."
        return out

    highs = pd.to_numeric(
        g["High"] if "High" in g.columns else g["Close"],
        errors="coerce",
    ).to_numpy(dtype=float)
    lows = pd.to_numeric(
        g["Low"] if "Low" in g.columns else g["Close"],
        errors="coerce",
    ).to_numpy(dtype=float)

    dates = (
        pd.to_datetime(g["Date"], errors="coerce").to_numpy(dtype="datetime64[ns]")
        if "Date" in g.columns
        else None
    )

    mfes: list[float] = []
    maes: list[float] = []
    days_list: list[int] = []
    tp_hits = 0
    cl_hits = 0
    sample = 0
    skipped_incomplete = 0
    skipped_gap = 0

    for i in range(14, last_i):
        row = g.iloc[i]
        if signal_mask is not None:
            try:
                if not bool(signal_mask.iloc[i]):
                    continue
            except Exception:
                continue
        elif signal_fn is not None:
            try:
                if not signal_fn(row):
                    continue
            except Exception:
                continue
        else:
            # Default: bars that would qualify under dynamic levels.
            pass

        levels = select_dynamic_levels(
            row,
            min_rr=min_rr,
            min_opportunity_pct=min_opportunity_pct,
        )
        if not levels.get("qualified"):
            continue

        entry = levels["entry_zone"]
        tp1 = levels["tp1"]
        if entry is None or tp1 is None:
            continue
        if i + horizon > n - 1:
            skipped_incomplete += 1
            continue
        if not _gap_free(dates, i, horizon):
            skipped_gap += 1
            continue

        mfe, mae, days = _forward_mfe_mae(highs, lows, float(entry), i, horizon)
        if mfe is None or mae is None:
            continue

        cl1 = levels.get("cl1")
        touch, touch_days = _first_touch(
            highs, lows, float(tp1), float(cl1) if cl1 is not None else None, i, horizon
        )
        sample += 1
        mfes.append(mfe)
        maes.append(mae)
        if touch == "TP":
            tp_hits += 1
        elif touch == "CL":
            cl_hits += 1
        if touch_days is not None:
            days_list.append(touch_days)
        elif days is not None:
            days_list.append(days)

    out["sample_size"] = sample
    out["outcome_basis"] = OUTCOME_BASIS
    out["skipped_incomplete_horizon"] = skipped_incomplete
    out["skipped_data_gap"] = skipped_gap
    if sample < min_sample:
        out["stats_status"] = STATUS_INSUFFICIENT_SAMPLE
        out["stats_note"] = (
            f"Sample size {sample} < {min_sample}; stats not statistically reliable."
        )
        # Still expose raw descriptive numbers when sample > 0, but marked insufficient.
        if sample > 0:
            out["mfe"] = round(float(np.median(mfes)), 3)
            out["mae"] = round(float(np.median(maes)), 3)
            out["historical_tp_probability"] = round(100.0 * tp_hits / sample, 2)
            out["historical_cl_probability"] = round(100.0 * cl_hits / sample, 2)
            if days_list:
                out["median_days"] = round(float(np.median(days_list)), 2)
        return out

    out["stats_status"] = "OK"
    out["stats_note"] = "Descriptive historical outcomes only — not a profitability claim."
    out["mfe"] = round(float(np.median(mfes)), 3)
    out["mae"] = round(float(np.median(maes)), 3)
    out["historical_tp_probability"] = round(100.0 * tp_hits / sample, 2)
    out["historical_cl_probability"] = round(100.0 * cl_hits / sample, 2)
    if days_list:
        out["median_days"] = round(float(np.median(days_list)), 2)
    return out


def historical_stats_for_frame(
    raw: pd.DataFrame,
    *,
    horizon: int = 10,
    min_opportunity_pct: float | None = None,
    signal_fn: Callable[[pd.Series], bool] | None = None,
) -> dict[str, Any]:
    enriched = enrich_structure(raw)
    return compute_historical_stats(
        enriched,
        signal_fn=signal_fn,
        horizon=horizon,
        min_opportunity_pct=min_opportunity_pct,
    )
