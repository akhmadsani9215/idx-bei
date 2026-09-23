"""Big Money — maximize disclosure / foreign / market-wide broker from available sources.

Never fabricates transaction-based Fast-In/Fast-Out or stock-specific broker actors.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from idx.core.ownership import (
    get_latest_shareholder_drift,
    load_ownership_csv,
    scan_ownership_files,
)
from idx.core.utils import DATA_DIR, load_json
from idx.schema_version import DATA_SCHEMA_VERSION
from idx.signals import broker_concentration_screen

ENGINE_VERSION = "big-money-1.1"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lineage(**kwargs: Any) -> dict[str, Any]:
    base = {
        "source": None,
        "as_of": None,
        "quality": "U",
        "confidence": None,
        "calculated_at": _utc(),
        "engine_version": ENGINE_VERSION,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "basis": "disclosure_or_aggregate",
    }
    base.update(kwargs)
    return base


def _ownership_for_ticker(code: str | None) -> dict[str, Any]:
    files = scan_ownership_files(DATA_DIR)
    if not files:
        return {
            "layer": "ownership_disclosure",
            "status": "UNAVAILABLE",
            "ticker": code,
            "basis": "disclosure",
            "records": 0,
            "top_holders": [],
            "concentration": None,
            "holder_changes": None,
            "note": (
                "No ownership CSV on disk. Provide path_or_url via Data Center ownership job."
            ),
            "lineage": _lineage(quality="U", basis="disclosure"),
        }

    latest = files[-1]
    try:
        df = load_ownership_csv(latest)
    except Exception as exc:
        return {
            "layer": "ownership_disclosure",
            "status": "UNAVAILABLE",
            "ticker": code,
            "basis": "disclosure",
            "records": 0,
            "top_holders": [],
            "concentration": None,
            "holder_changes": None,
            "note": f"Failed to parse ownership CSV: {exc}",
            "lineage": _lineage(source=latest, quality="U", basis="disclosure"),
        }

    # Normalize share code column
    code_col = None
    for c in ("ShareCode", "Code", "Ticker", "StockCode"):
        if c in df.columns:
            code_col = c
            break
    name_col = None
    for c in ("InvestorName", "INVESTOR_NAME", "Investor"):
        if c in df.columns:
            name_col = c
            break
    pct_col = None
    for c in ("Pct", "PERCENTAGE", "PctHolding"):
        if c in df.columns:
            pct_col = c
            break

    subset = df
    if code and code_col:
        subset = df[df[code_col].astype(str).str.upper() == code.upper()]

    top_holders: list[dict[str, Any]] = []
    concentration = None
    if len(subset) > 0 and pct_col:
        ordered = subset.sort_values(pct_col, ascending=False)
        for _, row in ordered.head(10).iterrows():
            top_holders.append(
                {
                    "investor": str(row[name_col]) if name_col else None,
                    "pct": float(row[pct_col]) if pd.notna(row[pct_col]) else None,
                    "basis": "disclosure",
                }
            )
        top3 = float(ordered.head(3)[pct_col].sum())
        top5 = float(ordered.head(5)[pct_col].sum())
        concentration = {
            "top3_pct": round(top3, 3),
            "top5_pct": round(top5, 3),
            "holder_count": int(len(ordered)),
            "basis": "disclosure",
        }

    # Holder changes only when ≥2 ownership snapshots exist (disclosure drift).
    holder_changes = None
    drift = get_latest_shareholder_drift(DATA_DIR)
    if drift.get("status") == "ok":
        deltas = drift.get("top_deltas") or []
        if code:
            filtered = [
                d
                for d in deltas
                if str(d.get("ShareCode") or d.get("code") or "").upper() == code
            ]
        else:
            filtered = deltas[:15]
        holder_changes = {
            "status": "PARTIAL",
            "basis": "disclosure",
            "prev_file": drift.get("prev_file"),
            "curr_file": drift.get("curr_file"),
            "total_deltas": drift.get("total_deltas"),
            "accumulations": drift.get("accumulations"),
            "distributions": drift.get("distributions"),
            "new_entries": drift.get("new_entries"),
            "exits": drift.get("exits"),
            "ticker_deltas": filtered,
            "note": "Disclosure-based month-over-month ownership drift — not transaction tape.",
        }
    elif drift.get("status") == "single_file":
        holder_changes = {
            "status": "PARTIAL",
            "basis": "disclosure",
            "note": "Only one ownership snapshot — concentration available; drift UNAVAILABLE.",
            "ticker_deltas": [],
        }
    else:
        holder_changes = {
            "status": "UNAVAILABLE",
            "basis": "disclosure",
            "note": "Insufficient ownership snapshots for drift.",
            "ticker_deltas": [],
        }

    status = "AVAILABLE" if len(subset) > 0 else ("PARTIAL" if len(df) > 0 else "UNAVAILABLE")
    note = (
        "Disclosure-based ownership (>1% KSEI-style CSV). Not transaction-based."
        if status != "UNAVAILABLE"
        else "No holders matched for ticker in ownership disclosure file."
    )
    if code and len(subset) == 0 and len(df) > 0:
        status = "PARTIAL"
        note = f"Ownership file present but no disclosure rows for {code}."

    return {
        "layer": "ownership_disclosure",
        "status": status,
        "ticker": code,
        "basis": "disclosure",
        "records": int(len(subset)),
        "top_holders": top_holders,
        "concentration": concentration,
        "holder_changes": holder_changes,
        "note": note,
        "lineage": _lineage(
            source=os.path.basename(latest),
            as_of=os.path.basename(latest),
            quality="C",
            confidence=0.55 if status == "AVAILABLE" else 0.35,
            basis="disclosure",
        ),
    }


def _foreign_layer(code: str | None, foreign_row: dict[str, Any] | None) -> dict[str, Any]:
    foreign = {
        "layer": "foreign_aggregate",
        "status": "UNAVAILABLE",
        "ticker": code,
        "basis": "aggregate_eod",
        "foreign_buy": None,
        "foreign_sell": None,
        "foreign_net": None,
        "note": "Foreign aggregate flow only — not smart-money / institutional attribution.",
        "lineage": _lineage(source="stock_summary", quality="B", basis="aggregate_eod"),
    }
    if not foreign_row:
        return foreign
    fb = foreign_row.get("foreign_buy")
    if fb is None:
        fb = foreign_row.get("ForeignBuy")
    fs = foreign_row.get("foreign_sell")
    if fs is None:
        fs = foreign_row.get("ForeignSell")
    try:
        fb_f = float(fb) if fb is not None and str(fb) != "nan" else None
        fs_f = float(fs) if fs is not None and str(fs) != "nan" else None
        foreign["foreign_buy"] = fb_f
        foreign["foreign_sell"] = fs_f
        if fb_f is not None and fs_f is not None:
            foreign["foreign_net"] = fb_f - fs_f
            foreign["status"] = "AVAILABLE"
            foreign["lineage"]["confidence"] = 0.6
            foreign["lineage"]["as_of"] = str(
                foreign_row.get("as_of") or foreign_row.get("Date") or ""
            )[:10] or None
        else:
            net = foreign_row.get("NetForeignFlow") or foreign_row.get("foreign_net")
            if net is not None and str(net) != "nan":
                foreign["foreign_net"] = float(net)
                foreign["status"] = "PARTIAL"
                foreign["lineage"]["confidence"] = 0.45
    except (TypeError, ValueError):
        foreign["status"] = "UNAVAILABLE"
    return foreign


def _broker_layer(broker_summary: Any) -> dict[str, Any]:
    broker = {
        "layer": "broker_market_wide",
        "status": "UNAVAILABLE",
        "scope": "MARKET-WIDE",
        "stock_specific": False,
        "basis": "market_wide_turnover",
        "concentration": None,
        "top_brokers": [],
        "note": "Broker summary is MARKET-WIDE. Not stock-specific actor attribution.",
        "lineage": _lineage(source="broker_summary", quality="C", basis="market_wide_turnover"),
    }
    if broker_summary is None:
        return broker
    try:
        if not isinstance(broker_summary, pd.DataFrame) or len(broker_summary) == 0:
            return broker
        summary, top_df = broker_concentration_screen(broker_summary, top_k=5)
        if not summary:
            return broker
        broker["status"] = "AVAILABLE"
        broker["concentration"] = {
            "cr1_pct": summary.get("cr1_pct"),
            "cr3_pct": summary.get("cr3_pct"),
            "cr5_pct": summary.get("cr5_pct"),
            "total_market_turnover_rp_b": summary.get("total_market_turnover_rp_b"),
            "top_dominant_broker": summary.get("top_dominant_broker"),
            "institutional_share_pct": None,  # never fabricate
            "retail_share_pct": None,
            "basis": "market_wide_turnover",
        }
        broker["top_brokers"] = top_df.to_dict("records") if len(top_df) else []
        broker["lineage"]["confidence"] = 0.55
        if "Date" in broker_summary.columns:
            as_of = pd.to_datetime(broker_summary["Date"], errors="coerce").max()
            if pd.notna(as_of):
                broker["lineage"]["as_of"] = as_of.strftime("%Y-%m-%d")
    except Exception as exc:
        broker["note"] = f"Broker concentration unavailable: {exc}"
    return broker


def build_big_money(
    *,
    ticker: str | None = None,
    broker_summary: Any = None,
    foreign_row: dict[str, Any] | None = None,
    ownership_available: bool | None = None,
) -> dict[str, Any]:
    """Build Big Money payload. ``ownership_available`` retained for tests."""
    code = (ticker or "").upper().strip() or None

    ownership = _ownership_for_ticker(code)
    if ownership_available is False:
        ownership = {
            "layer": "ownership_disclosure",
            "status": "UNAVAILABLE",
            "ticker": code,
            "basis": "disclosure",
            "records": 0,
            "top_holders": [],
            "concentration": None,
            "holder_changes": None,
            "note": "Ownership forced unavailable (test/override).",
            "lineage": _lineage(quality="U", basis="disclosure"),
        }

    foreign = _foreign_layer(code, foreign_row)
    broker = _broker_layer(broker_summary)

    # Stock-specific broker / actor transactions — always UNAVAILABLE with current sources
    stock_broker = {
        "layer": "broker_stock_specific",
        "status": "UNAVAILABLE",
        "ticker": code,
        "stock_specific": True,
        "note": "No verified stock↔broker transaction attribution in available sources.",
        "lineage": _lineage(quality="U"),
    }

    fast = {
        "layer": "fast_in_fast_out",
        "status": "UNAVAILABLE",
        "message": "DATA INSUFFICIENT FOR FAST-IN/FAST-OUT BACKTEST",
        "reason": (
            "Requires stock-specific broker/person transaction attribution "
            "which is not available in current sources."
        ),
        "entry": None,
        "exit": None,
        "return_pct": None,
        "mfe": None,
        "mae": None,
        "holding_period": None,
        "actor_identity": None,
        "institutional_classification": None,
        "lineage": _lineage(quality="U", confidence=None),
    }

    network = {
        "layer": "network_disclosure_cache",
        "status": "UNAVAILABLE",
        "basis": "disclosure_cache",
        "super_insiders": None,
        "conglomerates": None,
        "note": "Optional network_alpha_data.json disclosure cache — not transaction-based.",
        "lineage": _lineage(source="network_alpha_data.json", quality="D", basis="disclosure"),
    }
    alpha_path = os.path.join(DATA_DIR, "network_alpha_data.json")
    if os.path.isfile(alpha_path):
        try:
            blob = load_json(alpha_path)
            network["status"] = "PARTIAL"
            network["super_insiders"] = len(blob.get("super_insiders") or [])
            network["conglomerates"] = len(blob.get("conglomerates") or [])
            network["lineage"]["as_of"] = blob.get("last_updated")
            network["lineage"]["confidence"] = 0.35
            network["lineage"]["quality"] = "D"
        except Exception:
            network["status"] = "UNAVAILABLE"

    layers = {
        "ownership": ownership,
        "foreign": foreign,
        "broker": broker,
        "broker_stock_specific": stock_broker,
        "fast_in_fast_out": fast,
        "network": network,
    }
    statuses = [layers[k]["status"] for k in layers]
    if any(s == "AVAILABLE" for s in statuses):
        overall = "PARTIAL"  # Fast-In/Out always unavailable → never fully GREEN product-wise
    elif any(s == "PARTIAL" for s in statuses):
        overall = "PARTIAL"
    else:
        overall = "UNAVAILABLE"

    return {
        "ticker": code,
        "status": overall,
        "layers": layers,
        "data_inventory": {
            "ownership_disclosure": ownership["status"],
            "foreign_aggregate": foreign["status"],
            "broker_market_wide": broker["status"],
            "broker_stock_specific": "UNAVAILABLE",
            "actor_level_transaction": "UNAVAILABLE",
            "historical_ownership_drift": (
                (ownership.get("holder_changes") or {}).get("status") or "UNAVAILABLE"
            ),
        },
        "engine_version": ENGINE_VERSION,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "calculated_at": _utc(),
    }
