"""Feature / Target-Risk rebuild — on-read snapshot using existing screener functions.

Does not mutate source market partitions. Writes deterministic cache artifacts only.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from idx.core.utils import DATA_DIR
from idx.schema_version import DATA_SCHEMA_VERSION
from idx.screener.contract import ENGINE_VERSION as SCREENER_ENGINE
from idx.screener.structure import enrich_structure, select_dynamic_levels
from idx.universe import discover_universe

FEATURE_CACHE = os.path.join(DATA_DIR, ".feature_rebuild_cache.json")
TARGET_RISK_CACHE = os.path.join(DATA_DIR, ".target_risk_rebuild_cache.json")
ENGINE_VERSION = "rebuild-1.0"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


def rebuild_features(
    *,
    stock_df: pd.DataFrame | None = None,
    max_tickers: int = 50,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Compute structure features for a capped universe; write cache. Source OHLC untouched."""
    started = _utc()
    t0 = time.perf_counter()
    warnings: list[str] = []
    errors: list[str] = []
    records = 0

    try:
        uni = discover_universe(stock_df, as_of=as_of)
        tickers = uni.get("tickers") or []
        if len(tickers) > max_tickers:
            warnings.append(
                f"Universe {len(tickers)} capped to max_tickers={max_tickers} for rebuild safety."
            )
            tickers = tickers[:max_tickers]

        if stock_df is None:
            from idx.core.query import query_dataset

            raw = query_dataset("stock_summary", end=as_of)
        else:
            raw = stock_df.copy()

        rows: list[dict[str, Any]] = []
        for code in tickers:
            try:
                g = raw[raw["StockCode"].astype(str).str.upper() == code]
                if len(g) < 20:
                    warnings.append(f"{code}: insufficient bars")
                    continue
                enriched = enrich_structure(g)
                last = enriched.iloc[-1]
                rows.append(
                    {
                        "ticker": code,
                        "as_of": str(last.get("Date"))[:10],
                        "close": float(last["Close"]) if pd.notna(last.get("Close")) else None,
                        "atr14": float(last["ATR14"]) if pd.notna(last.get("ATR14")) else None,
                        "rvol": float(last["RVOL"]) if pd.notna(last.get("RVOL")) else None,
                        "high_20d": float(last["HIGH_20D"]) if pd.notna(last.get("HIGH_20D")) else None,
                        "low_20d": float(last["LOW_20D"]) if pd.notna(last.get("LOW_20D")) else None,
                        "engine_version": SCREENER_ENGINE,
                    }
                )
                records += 1
            except Exception as exc:
                errors.append(f"{code}: {exc}")

        payload = {
            "status": "SUCCESS" if records and not errors else ("PARTIAL" if records else "FAILED"),
            "started_at": started,
            "completed_at": _utc(),
            "duration_sec": round(time.perf_counter() - t0, 3),
            "records": records,
            "warnings": warnings,
            "errors": errors,
            "engine_version": ENGINE_VERSION,
            "screener_engine_version": SCREENER_ENGINE,
            "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
            "source": "stock_summary (read-only)",
            "mutates_source": False,
            "rows": rows,
            "as_of": uni.get("as_of"),
            "universe_total": uni.get("universe_total"),
        }
        _write_json(FEATURE_CACHE, {k: v for k, v in payload.items() if k != "rows"})
        # Keep rows in returned payload; cache meta without giant rows optional — store compact
        _write_json(
            FEATURE_CACHE,
            {**{k: v for k, v in payload.items() if k != "rows"}, "sample_rows": rows[:20]},
        )
        return payload
    except Exception as exc:
        return {
            "status": "FAILED",
            "started_at": started,
            "completed_at": _utc(),
            "duration_sec": round(time.perf_counter() - t0, 3),
            "records": 0,
            "warnings": warnings,
            "errors": [str(exc)],
            "engine_version": ENGINE_VERSION,
            "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
            "mutates_source": False,
        }


def rebuild_target_risk(
    *,
    stock_df: pd.DataFrame | None = None,
    max_tickers: int = 50,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Deterministic TP/CL from structure snapshot; does not mutate source."""
    started = _utc()
    t0 = time.perf_counter()
    warnings: list[str] = []
    errors: list[str] = []
    records = 0
    try:
        uni = discover_universe(stock_df, as_of=as_of)
        tickers = uni.get("tickers") or []
        if len(tickers) > max_tickers:
            warnings.append(
                f"Universe {len(tickers)} capped to max_tickers={max_tickers} for rebuild safety."
            )
            tickers = tickers[:max_tickers]

        if stock_df is None:
            from idx.core.query import query_dataset

            raw = query_dataset("stock_summary", end=as_of)
        else:
            raw = stock_df.copy()

        rows: list[dict[str, Any]] = []
        for code in tickers:
            try:
                g = raw[raw["StockCode"].astype(str).str.upper() == code]
                if len(g) < 20:
                    warnings.append(f"{code}: insufficient bars")
                    continue
                enriched = enrich_structure(g)
                levels = select_dynamic_levels(enriched.iloc[-1], min_rr=2.0)
                rows.append(
                    {
                        "ticker": code,
                        "qualified": bool(levels.get("qualified")),
                        "entry_zone": levels.get("entry_zone"),
                        "tp1": levels.get("tp1"),
                        "cl1": levels.get("cl1"),
                        "rr1": levels.get("rr1"),
                        "tp1_source": levels.get("tp1_source"),
                        "cl1_source": levels.get("cl1_source"),
                    }
                )
                records += 1
            except Exception as exc:
                errors.append(f"{code}: {exc}")

        payload = {
            "status": "SUCCESS" if records and not errors else ("PARTIAL" if records else "FAILED"),
            "started_at": started,
            "completed_at": _utc(),
            "duration_sec": round(time.perf_counter() - t0, 3),
            "records": records,
            "warnings": warnings,
            "errors": errors,
            "engine_version": ENGINE_VERSION,
            "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
            "source": "stock_summary + idx.screener.structure (read-only)",
            "mutates_source": False,
            "as_of": uni.get("as_of"),
            "universe_total": uni.get("universe_total"),
            "sample_rows": rows[:20],
        }
        _write_json(TARGET_RISK_CACHE, payload)
        payload["rows"] = rows
        return payload
    except Exception as exc:
        return {
            "status": "FAILED",
            "started_at": started,
            "completed_at": _utc(),
            "duration_sec": round(time.perf_counter() - t0, 3),
            "records": 0,
            "warnings": warnings,
            "errors": [str(exc)],
            "engine_version": ENGINE_VERSION,
            "mutates_source": False,
        }
