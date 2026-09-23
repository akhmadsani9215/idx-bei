"""Stock Terminal payload — compact chart + honest capability flags."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from idx.providers import MarketDataProvider
from idx.schema_version import DATA_SCHEMA_VERSION, attach_schema
from idx.screener.engine import evaluate_close_pressure_row, evaluate_swing_row
from idx.screener.structure import enrich_structure
from idx.signals import compute_technical_indicators

ENGINE_VERSION = "terminal-1.0"


def build_stock_terminal(
    df: pd.DataFrame,
    ticker: str,
    *,
    limit: int = 120,
    company: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    provider = MarketDataProvider().status().to_dict()

    if df is None or len(df) == 0:
        return attach_schema(
            {
                "ticker": ticker,
                "status": "UNAVAILABLE",
                "company": company,
                "price": None,
                "change": None,
                "change_pct": None,
                "records": [],
                "latest": {},
                "foreign": None,
                "screener": None,
                "orderbook": {
                    "status": "NOT_CONFIGURED",
                    "message": "ORDERBOOK NOT CONFIGURED",
                },
                "tape": {
                    "status": "NOT_CONFIGURED",
                    "message": "TRANSACTION TAPE NOT CONFIGURED",
                },
                "broker": {
                    "scope": "MARKET-WIDE",
                    "stock_specific": False,
                    "status": "UNAVAILABLE",
                    "note": "Use /api/broker-flow for market-wide concentration only.",
                },
                "data_quality": "U",
                "source": None,
                "as_of": None,
                "confidence": None,
                "provider": provider,
                "engine_version": ENGINE_VERSION,
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    work = df.copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    work["_date_key"] = work["Date"].dt.strftime("%Y-%m-%d")
    work = work.drop_duplicates(subset=["_date_key"], keep="last").drop(columns=["_date_key"])

    tech = compute_technical_indicators(work, ticker=ticker)
    if limit and limit > 0 and len(tech) > limit:
        tech = tech.tail(limit).reset_index(drop=True)

    tech["time"] = tech["Date"].dt.strftime("%Y-%m-%d")
    tech["open"] = tech["OpenPrice"].fillna(tech["Close"]) if "OpenPrice" in tech.columns else tech["Close"]
    tech["high"] = tech["High"].fillna(tech["Close"]) if "High" in tech.columns else tech["Close"]
    tech["low"] = tech["Low"].fillna(tech["Close"]) if "Low" in tech.columns else tech["Close"]
    tech["close"] = tech["Close"]
    tech["volume"] = tech["Volume"].fillna(0) if "Volume" in tech.columns else 0

    keep_cols = [
        c
        for c in (
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "value",
            "RSI14",
            "EMA20",
            "EMA50",
            "EMA200",
            "BB_Upper",
            "BB_Lower",
            "BB_PctB",
            "ATR14",
            "VolRatio20",
            "TrendRegime",
            "ForeignBuy",
            "ForeignSell",
            "NetForeignFlow",
        )
        if c in tech.columns or c == "value"
    ]
    if "Value" in tech.columns:
        tech["value"] = tech["Value"]
    out_df = tech[[c for c in keep_cols if c in tech.columns]].copy()

    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for rec in frame.to_dict(orient="records"):
            clean: dict[str, Any] = {}
            for k, v in rec.items():
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    clean[k] = None
                elif hasattr(v, "item"):
                    try:
                        clean[k] = v.item()
                    except Exception:
                        clean[k] = None if pd.isna(v) else v
                else:
                    clean[k] = v
            rows.append(clean)
        return rows

    records = _records(out_df)
    latest = records[-1] if records else {}

    price = latest.get("close")
    change = None
    change_pct = None
    if len(records) >= 2 and price is not None and records[-2].get("close"):
        try:
            prev = float(records[-2]["close"])
            price_f = float(price)
            change = price_f - prev
            change_pct = (change / prev) * 100.0 if prev else None
        except (TypeError, ValueError):
            pass

    foreign = {
        "foreign_buy": latest.get("ForeignBuy"),
        "foreign_sell": latest.get("ForeignSell"),
        "net": latest.get("NetForeignFlow"),
        "status": "PARTIAL" if latest.get("ForeignBuy") is not None or latest.get("NetForeignFlow") is not None else "UNAVAILABLE",
        "note": "Aggregate foreign flow — not institutional attribution.",
        "as_of": latest.get("time"),
        "source": "stock_summary",
        "quality": "B",
    }

    enriched = enrich_structure(work)
    screener_cp = evaluate_close_pressure_row(enriched, company=(company or {}).get("name"))
    screener_sw = evaluate_swing_row(enriched, company=(company or {}).get("name"))

    return attach_schema(
        {
            "ticker": ticker,
            "status": "ok",
            "company": company,
            "price": price,
            "change": change,
            "change_pct": change_pct,
            "records": records,
            "latest": latest,
            "foreign": foreign,
            "screener": {
                "close_pressure": {
                    "setup": screener_cp.get("setup"),
                    "signal": screener_cp.get("signal"),
                    "engine_score": screener_cp.get("engine_score"),
                    "entry_zone": screener_cp.get("entry_zone"),
                    "tp1": screener_cp.get("tp1"),
                    "tp2": screener_cp.get("tp2"),
                    "tp3": screener_cp.get("tp3"),
                    "cl1": screener_cp.get("cl1"),
                    "cl2": screener_cp.get("cl2"),
                    "cl3": screener_cp.get("cl3"),
                    "rr1": screener_cp.get("rr1"),
                    "data_quality": screener_cp.get("data_quality"),
                    "confidence": screener_cp.get("confidence"),
                    "why_signal": screener_cp.get("why_signal"),
                    "as_of": screener_cp.get("as_of"),
                    "lifecycle": screener_cp.get("lifecycle"),
                },
                "swing": {
                    "setup": screener_sw.get("setup"),
                    "signal": screener_sw.get("signal"),
                    "why_signal": screener_sw.get("why_signal"),
                    "data_quality": screener_sw.get("data_quality"),
                    "as_of": screener_sw.get("as_of"),
                },
            },
            "orderbook": {
                "status": "NOT_CONFIGURED",
                "message": "ORDERBOOK NOT CONFIGURED",
            },
            "tape": {
                "status": "NOT_CONFIGURED",
                "message": "TRANSACTION TAPE NOT CONFIGURED",
            },
            "broker": {
                "scope": "MARKET-WIDE",
                "stock_specific": False,
                "status": "UNAVAILABLE",
                "note": "Stock-specific broker blocks unavailable. Market-wide via /api/broker-flow.",
            },
            "data_quality": "B",
            "source": "stock_summary",
            "as_of": latest.get("time"),
            "confidence": 0.65,
            "provider": provider,
            "realtime": "NOT_CONFIGURED",
            "engine_version": ENGINE_VERSION,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
