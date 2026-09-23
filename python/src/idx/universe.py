"""Deterministic universe discovery from local stock_summary partitions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from idx.schema_version import DATA_SCHEMA_VERSION

ENGINE_VERSION = "universe-1.0"


def discover_universe(
    stock_df: pd.DataFrame | None = None,
    *,
    as_of: str | None = None,
    base_dir: str | None = None,
) -> dict[str, Any]:
    """Return sorted unique tickers from local OHLC — never from network_alpha."""
    calculated_at = datetime.now(timezone.utc).isoformat()
    tickers: list[str] = []
    source = "injected_frame"
    as_of_out = as_of

    if stock_df is not None and len(stock_df) > 0:
        df = stock_df.copy()
        if as_of and "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df[df["Date"] <= pd.Timestamp(as_of)]
            if len(df) and pd.notna(df["Date"].max()):
                as_of_out = pd.Timestamp(df["Date"].max()).strftime("%Y-%m-%d")
        if "StockCode" in df.columns:
            tickers = sorted({str(x).upper().strip() for x in df["StockCode"].dropna().unique()})
    else:
        source = "stock_summary_distinct"
        try:
            from idx.core.query import query_dataset

            # Lightweight: ask DuckDB for distinct codes (may still scan parquet).
            df = query_dataset(
                "stock_summary",
                columns="StockCode, Date",
                end=as_of,
                base_dir=base_dir,
            )
            if len(df) and "StockCode" in df.columns:
                tickers = sorted(
                    {str(x).upper().strip() for x in df["StockCode"].dropna().unique()}
                )
            if len(df) and "Date" in df.columns:
                mx = pd.to_datetime(df["Date"], errors="coerce").max()
                if pd.notna(mx):
                    as_of_out = mx.strftime("%Y-%m-%d")
        except Exception as exc:
            return {
                "tickers": [],
                "universe_total": 0,
                "as_of": as_of_out,
                "source": source,
                "status": "UNAVAILABLE",
                "error": str(exc),
                "engine_version": ENGINE_VERSION,
                "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
                "calculated_at": calculated_at,
            }

    return {
        "tickers": tickers,
        "universe_total": len(tickers),
        "as_of": as_of_out,
        "source": source,
        "status": "AVAILABLE" if tickers else "UNAVAILABLE",
        "network_alpha_required": False,
        "engine_version": ENGINE_VERSION,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "calculated_at": calculated_at,
    }


def apply_universe_cap(
    tickers: list[str],
    *,
    max_universe: int | None,
    cursor: int = 0,
) -> dict[str, Any]:
    """Explicit cap — never silent. Returns slice metadata."""
    total = len(tickers)
    if max_universe is None or max_universe <= 0:
        selected = tickers
        capped = False
        skipped = 0
    else:
        capped = total > max_universe
        selected = tickers[:max_universe]
        skipped = max(0, total - len(selected))
    # Pagination over selected set
    page = selected[cursor:] if cursor else selected
    return {
        "tickers": page,
        "universe_total": total,
        "universe_selected": len(selected),
        "universe_capped": capped,
        "skipped_due_to_cap": skipped,
        "max_universe": max_universe,
        "cursor": cursor,
    }
