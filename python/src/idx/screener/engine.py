"""Screener production engine: DATA → FEATURE → SIGNAL → TARGET → RISK → STATS.

Modes: close_pressure | swing | long_term.
Honest PARTIAL / UNAVAILABLE / NOT_QUALIFIED — no fabricated TP/CL/%.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from idx.close_pressure_config import WINDOW, classify_time_window
from idx.core.utils import DATA_DIR, load_json
from idx.screener.contract import (
    ENGINE_VERSION,
    MIN_OPPORTUNITY_PCT,
    MIN_RR,
    PRODUCTION_ELIGIBILITY_REASON,
    PRODUCTION_ELIGIBILITY_STATUS,
    SETUP_NOT_QUALIFIED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    TIMEFRAMES,
    base_result,
    empty_lineage,
    sanitize_result,
)
from idx.screener.historical import compute_historical_stats
from idx.screener.structure import (
    classify_lifecycle,
    close_pressure_proxy_score,
    detect_swing_setup,
    enrich_structure,
    select_dynamic_levels,
)

try:
    from idx.core.query import query_dataset
except Exception:  # pragma: no cover — tests inject frames
    query_dataset = None  # type: ignore


def _as_of_str(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%d")
    except Exception:
        s = str(value)
        return s[:10] if s else None


def _trend_label(row: pd.Series) -> str | None:
    sma20 = row.get("SMA20")
    sma50 = row.get("SMA50")
    close = row.get("Close")
    if pd.isna(close) or pd.isna(sma20):
        return None
    close_f = float(close)
    s20 = float(sma20)
    if pd.notna(sma50):
        s50 = float(sma50)
        if close_f > s20 > s50:
            return "UPTREND"
        if close_f < s20 < s50:
            return "DOWNTREND"
    if close_f > s20:
        return "ABOVE_SMA20"
    if close_f < s20:
        return "BELOW_SMA20"
    return "NEUTRAL"


def _load_company_meta() -> dict[str, dict[str, Any]]:
    path = os.path.join(DATA_DIR, "network_alpha_data.json")
    if not os.path.exists(path):
        return {}
    try:
        data = load_json(path)
    except Exception:
        return {}
    companies = data.get("companies") if isinstance(data, dict) else None
    if not isinstance(companies, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for c in companies:
        if not isinstance(c, dict):
            continue
        code = str(c.get("code") or c.get("StockCode") or "").upper().strip()
        if not code:
            continue
        out[code] = c
    return out


def _load_stock_frame(
    ticker: str | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
    injected: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if injected is not None:
        df = injected.copy()
    else:
        if query_dataset is None:
            return pd.DataFrame()
        where = None
        if ticker:
            safe = ticker.upper().replace("'", "")
            where = f"StockCode = '{safe}'"
        try:
            df = query_dataset("stock_summary", start=start, end=end, where=where)
        except Exception:
            return pd.DataFrame()

    if df is None or len(df) == 0:
        return pd.DataFrame()

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).sort_values(
            ["StockCode", "Date"] if "StockCode" in df.columns else ["Date"]
        )
    return df.reset_index(drop=True)


def evaluate_close_pressure_row(
    enriched: pd.DataFrame,
    *,
    company: str | None = None,
    now_jakarta: datetime | None = None,
) -> dict[str, Any]:
    """Build one Close Pressure screener result from EOD-enriched history."""
    if enriched is None or len(enriched) == 0:
        row = base_result(ticker="?", timeframe="close_pressure")
        row["status"] = STATUS_UNAVAILABLE
        row["why_signal"] = "No OHLC history available."
        return sanitize_result(row)

    last = enriched.iloc[-1]
    ticker = str(last.get("StockCode") or "?").upper()
    result = base_result(ticker=ticker, company=company, timeframe="close_pressure")
    as_of = _as_of_str(last.get("Date"))

    result["price"] = float(last["Close"]) if pd.notna(last.get("Close")) else None
    prev = last.get("Previous")
    if result["price"] is not None and pd.notna(prev):
        result["change"] = result["price"] - float(prev)
        if float(prev) > 0:
            result["change_pct"] = (result["change"] / float(prev)) * 100.0
    elif result["price"] is not None and len(enriched) >= 2:
        prior_close = enriched.iloc[-2].get("Close")
        if pd.notna(prior_close) and float(prior_close) > 0:
            result["change"] = result["price"] - float(prior_close)
            result["change_pct"] = (result["change"] / float(prior_close)) * 100.0

    result["volume"] = float(last["Volume"]) if pd.notna(last.get("Volume")) else None
    result["value"] = float(last["Value"]) if pd.notna(last.get("Value")) else None
    result["trend"] = _trend_label(last)
    result["lifecycle"] = classify_lifecycle(last)
    result["foreign"] = (
        float(last["FOREIGN_NET_5D"]) if pd.notna(last.get("FOREIGN_NET_5D")) else None
    )
    result["liquidity"] = result["value"]

    pressure_score, pressure_label, why = close_pressure_proxy_score(last)
    result["pressure"] = pressure_score
    result["engine_score"] = pressure_score

    # EOD-only: quality E. Never claim Bid/Offer as trade dominance.
    result["data_quality"] = "E"
    result["source"] = "stock_summary_eod"
    result["as_of"] = as_of
    result["confidence"] = 0.35 if pressure_score is not None else 0.15
    result["status"] = STATUS_PARTIAL
    result["signal"] = pressure_label

    phase = None
    if now_jakarta is not None:
        phase = classify_time_window(now_jakarta.time())
        why = [f"Internal CPE window: {phase}", *why]
        if phase == "OUTSIDE":
            why.append("Outside Close Pressure windows (14:30–16:02); EOD proxy retained")
        elif phase == "PRE_CLOSING":
            why.append("PRE_CLOSING (15:50–16:00) — not continuous normal trading")
        elif phase == "PRIMARY_SIGNAL":
            why.append("PRIMARY_SIGNAL window (15:30–15:50)")
    else:
        why = [
            "No live Jakarta clock provided — EOD evaluation only",
            f"Configured windows: WATCH≥{WINDOW.watch_start.strftime('%H:%M')} "
            f"PRIMARY={WINDOW.primary_start.strftime('%H:%M')}–{WINDOW.primary_end.strftime('%H:%M')} "
            f"PRE_CLOSING={WINDOW.preclose_start.strftime('%H:%M')}–{WINDOW.preclose_end.strftime('%H:%M')}",
            *why,
        ]

    levels = select_dynamic_levels(
        last,
        min_rr=MIN_RR,
        min_opportunity_pct=MIN_OPPORTUNITY_PCT,
    )
    for k, v in levels.items():
        if k in ("qualified", "setup_status"):
            continue
        result[k] = v

    if levels.get("qualified"):
        result["setup"] = "close_pressure"
        result["signal"] = pressure_label or "CLOSE_PRESSURE"
    else:
        result["setup"] = SETUP_NOT_QUALIFIED
        why.append("No Entry+TP+CL pair with RR≥1:2 and ≥+3% opportunity — NOT QUALIFIED")

    # Historical stats: exclude live bar; no profitability claim.
    def _cp_signal(r: pd.Series) -> bool:
        score, _, _ = close_pressure_proxy_score(r)
        if score is None or score < 55:
            return False
        lv = select_dynamic_levels(r, min_rr=MIN_RR, min_opportunity_pct=MIN_OPPORTUNITY_PCT)
        return bool(lv.get("qualified"))

    hist = compute_historical_stats(
        enriched,
        signal_fn=_cp_signal,
        horizon=5,
        min_opportunity_pct=MIN_OPPORTUNITY_PCT,
    )
    result.update(hist)

    result["why_signal"] = "; ".join(why)
    result["lineage"] = empty_lineage(
        source=result["source"],
        as_of=as_of,
        quality="E",
        confidence=result["confidence"],
    )
    result["cpe_phase"] = phase
    result["intraday_trade_side_available"] = False
    result["book_pressure_is_transaction"] = False
    return sanitize_result(result)


def evaluate_swing_row(
    enriched: pd.DataFrame,
    *,
    company: str | None = None,
) -> dict[str, Any]:
    if enriched is None or len(enriched) == 0:
        row = base_result(ticker="?", timeframe="swing")
        row["status"] = STATUS_UNAVAILABLE
        row["why_signal"] = "No OHLC history available."
        return sanitize_result(row)

    last = enriched.iloc[-1]
    ticker = str(last.get("StockCode") or "?").upper()
    result = base_result(ticker=ticker, company=company, timeframe="swing")
    as_of = _as_of_str(last.get("Date"))

    result["price"] = float(last["Close"]) if pd.notna(last.get("Close")) else None
    result["volume"] = float(last["Volume"]) if pd.notna(last.get("Volume")) else None
    result["value"] = float(last["Value"]) if pd.notna(last.get("Value")) else None
    if result["price"] is not None and len(enriched) >= 2:
        prior_close = enriched.iloc[-2].get("Close")
        if pd.notna(prior_close) and float(prior_close) > 0:
            result["change"] = result["price"] - float(prior_close)
            result["change_pct"] = (result["change"] / float(prior_close)) * 100.0

    result["trend"] = _trend_label(last)
    result["lifecycle"] = classify_lifecycle(last)
    result["foreign"] = (
        float(last["FOREIGN_NET_5D"]) if pd.notna(last.get("FOREIGN_NET_5D")) else None
    )
    result["liquidity"] = result["value"]
    result["data_quality"] = "B" if len(enriched) >= 60 else "C"
    result["source"] = "stock_summary_daily"
    result["as_of"] = as_of
    result["status"] = STATUS_PARTIAL

    setup = detect_swing_setup(last)
    why: list[str] = []
    if setup is None:
        result["setup"] = SETUP_NOT_QUALIFIED
        result["signal"] = None
        result["confidence"] = 0.25
        why.append("No swing setup detectable from available daily structure")
    else:
        result["signal"] = setup
        why.append(f"Swing setup={setup} (separate engine from Close Pressure)")

    levels = select_dynamic_levels(last, min_rr=MIN_RR, min_opportunity_pct=None)
    for k, v in levels.items():
        if k in ("qualified", "setup_status"):
            continue
        result[k] = v

    if setup and levels.get("qualified"):
        result["setup"] = f"swing_{setup}"
        result["engine_score"] = 70.0
        result["confidence"] = 0.55 if result["data_quality"] == "B" else 0.4
    else:
        result["setup"] = SETUP_NOT_QUALIFIED
        result["engine_score"] = None
        result["confidence"] = 0.3
        why.append("RR≥1:2 not met or levels unavailable — NOT QUALIFIED")

    def _swing_signal(r: pd.Series) -> bool:
        s = detect_swing_setup(r)
        if not s:
            return False
        return bool(select_dynamic_levels(r, min_rr=MIN_RR).get("qualified"))

    hist = compute_historical_stats(
        enriched,
        signal_fn=_swing_signal,
        horizon=20,
        min_opportunity_pct=None,
    )
    result.update(hist)
    result["why_signal"] = "; ".join(why)
    result["lineage"] = empty_lineage(
        source=result["source"],
        as_of=as_of,
        quality=result["data_quality"],
        confidence=result["confidence"],
    )
    return sanitize_result(result)


def evaluate_long_term_candidate(
    *,
    ticker: str,
    company_meta: dict[str, Any] | None,
    enriched: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Long-term CANDIDATE using available fundamentals — never 'guaranteed multibagger'."""
    meta = company_meta or {}
    name = meta.get("name") or meta.get("StockName") or ticker
    result = base_result(ticker=ticker, company=name, timeframe="long_term")
    result["signal"] = "CANDIDATE"
    result["setup"] = "long_term_candidate"
    result["source"] = "network_alpha_fundamentals" if meta else None

    roe = meta.get("roe")
    per = meta.get("per")
    pbv = meta.get("price_bv") if meta.get("price_bv") is not None else meta.get("pbv")
    npm = meta.get("npm")
    der = meta.get("de_ratio")
    dyield = meta.get("yield")
    close = meta.get("close") if meta.get("close") is not None else meta.get("price")

    structure_qualified = False
    if enriched is not None and len(enriched) > 0:
        last = enriched.iloc[-1]
        result["as_of"] = _as_of_str(last.get("Date"))
        result["price"] = float(last["Close"]) if pd.notna(last.get("Close")) else None
        result["trend"] = _trend_label(last)
        result["lifecycle"] = classify_lifecycle(last)
        # Optional structure levels — null when RR gate fails (do not fabricate).
        levels = select_dynamic_levels(last, min_rr=MIN_RR, min_opportunity_pct=None)
        if levels.get("qualified"):
            structure_qualified = True
            for k, v in levels.items():
                if k in ("qualified", "setup_status"):
                    continue
                result[k] = v
    else:
        result["price"] = float(close) if close is not None else None
        result["as_of"] = meta.get("price_date")

    # Count available fundamental fields.
    fields = {
        "roe": roe,
        "per": per,
        "price_bv": pbv,
        "npm": npm,
        "de_ratio": der,
        "yield": dyield,
    }
    present = {k: v for k, v in fields.items() if v is not None and v != ""}
    missing = [k for k, v in fields.items() if k not in present]

    why = ["Label=CANDIDATE (not a guaranteed multibagger)"]
    score = 0.0
    if present.get("roe") is not None:
        try:
            rv = float(present["roe"])
            if rv >= 15:
                score += 30
                why.append(f"ROE {rv:.1f}%")
            elif rv >= 8:
                score += 15
                why.append(f"ROE {rv:.1f}% (moderate)")
        except (TypeError, ValueError):
            missing.append("roe")
    if present.get("per") is not None:
        try:
            pv = float(present["per"])
            if 0 < pv < 15:
                score += 20
                why.append(f"PER {pv:.1f}")
            elif 0 < pv < 25:
                score += 8
        except (TypeError, ValueError):
            pass
    if present.get("price_bv") is not None:
        try:
            bv = float(present["price_bv"])
            if 0 < bv < 1.5:
                score += 15
                why.append(f"PBV {bv:.2f}")
        except (TypeError, ValueError):
            pass
    if present.get("npm") is not None:
        try:
            nv = float(present["npm"])
            if nv > 0:
                score += 10
                why.append(f"NPM {nv:.1f}%")
        except (TypeError, ValueError):
            pass
    if present.get("de_ratio") is not None:
        try:
            dv = float(present["de_ratio"])
            if dv <= 1.5:
                score += 10
                why.append(f"DER {dv:.2f}")
            elif dv > 3:
                score -= 10
                why.append(f"High DER {dv:.2f}")
        except (TypeError, ValueError):
            pass
    if present.get("yield") is not None:
        try:
            yv = float(present["yield"])
            if yv >= 3:
                score += 10
                why.append(f"Yield {yv:.1f}%")
        except (TypeError, ValueError):
            pass

    if enriched is not None and len(enriched) >= 50 and result.get("trend") == "UPTREND":
        score += 10
        why.append("Daily structure uptrend (SMA20>SMA50)")

    if len(present) < 3:
        result["status"] = STATUS_INSUFFICIENT_DATA
        result["setup"] = SETUP_NOT_QUALIFIED
        result["data_quality"] = "U" if not present else "D"
        result["confidence"] = 0.2
        result["engine_score"] = None
        why.append(f"INSUFFICIENT DATA — missing {', '.join(missing) or 'fundamentals'}")
        result["why_signal"] = "; ".join(why)
        result["historical_tp_probability"] = None
        result["sample_size"] = 0
        result["stats_status"] = STATUS_UNAVAILABLE
        result["stats_note"] = "Long-term historical expectancy not validated for production."
        return sanitize_result(result)

    result["setup"] = "long_term_candidate"
    result["engine_score"] = round(min(100.0, max(0.0, score)), 1)
    result["data_quality"] = "C"
    result["confidence"] = 0.45
    result["status"] = STATUS_PARTIAL
    if missing:
        why.append(f"PARTIAL fundamentals — missing {', '.join(missing)}")
    if not structure_qualified:
        why.append("Structure TP/CL NOT QUALIFIED (RR gate) — levels left null")
    result["why_signal"] = "; ".join(why)
    # Do not invent historical TP stats for long-term without a validated engine.
    result["historical_tp_probability"] = None
    result["mfe"] = None
    result["mae"] = None
    result["median_days"] = None
    result["sample_size"] = 0
    result["stats_status"] = STATUS_UNAVAILABLE
    result["stats_note"] = (
        "Long-term historical stats unavailable — no validated LT backtest wired."
    )
    result["lineage"] = empty_lineage(
        source=result["source"],
        as_of=result.get("as_of"),
        quality=result["data_quality"],
        confidence=result["confidence"],
    )
    return sanitize_result(result)


def run_screener(
    *,
    timeframe: str = "close_pressure",
    ticker: str | None = None,
    date: str | None = None,
    setup: str | None = None,
    signal: str | None = None,
    limit: int = 25,
    cursor: int = 0,
    stock_df: pd.DataFrame | None = None,
    company_meta: dict[str, dict[str, Any]] | None = None,
    now_jakarta: datetime | None = None,
    include_not_qualified: bool = False,
    max_universe: int = 80,
) -> dict[str, Any]:
    """Server-side screener. Returns paginated results + meta limitations."""
    tf = (timeframe or "close_pressure").strip().lower()
    if tf not in TIMEFRAMES:
        return {
            "results": [],
            "meta": {
                "status": "error",
                "error": f"Unknown timeframe '{timeframe}'. Expected one of {TIMEFRAMES}.",
                "engine_version": ENGINE_VERSION,
            },
        }

    limit = max(1, min(int(limit or 25), 100))
    cursor = max(0, int(cursor or 0))
    max_universe = max(1, min(int(max_universe or 80), 300))

    # network_alpha is OPTIONAL meta only — never a mandatory dependency.
    meta_map = company_meta if company_meta is not None else _load_company_meta()
    raw = _load_stock_frame(ticker, end=date, injected=stock_df)

    results: list[dict[str, Any]] = []
    universe_total = 0
    scanned = 0
    limitations = [
        "production_eligibility=NOT_VALIDATED — no setup survived OOS/walk-forward/robustness/cost gates.",
        "Close Pressure uses EOD proxies — BidVolume/OfferVolume are NOT trade-side dominance.",
        "Dynamic TP/CL from structure only; RR≥1:2 required or NOT_QUALIFIED.",
        "Historical stats are descriptive; not a production profitability claim.",
        "Cost/slippage NOT_CONFIGURED; survivorship NOT_VALIDATED.",
        "No intraday tick/orderbook feed configured.",
        "network_alpha_data.json is optional company meta — not required for OHLC screening.",
    ]

    if raw is None or len(raw) == 0:
        return {
            "results": [],
            "meta": {
                "status": STATUS_UNAVAILABLE,
                "timeframe": tf,
                "as_of": date,
                "count": 0,
                "limit": limit,
                "cursor": cursor,
                "next_cursor": None,
                "universe_total": 0,
                "universe_scanned": 0,
                "universe_capped": False,
                "max_universe": max_universe,
                "network_alpha_required": False,
            "engine_version": ENGINE_VERSION,
            "production_eligibility": PRODUCTION_ELIGIBILITY_STATUS,
            "production_eligibility_reason": PRODUCTION_ELIGIBILITY_REASON,
            "limitations": limitations,
            "note": "No stock_summary rows available for screener.",
            },
        }

    if "StockCode" not in raw.columns:
        raw = raw.copy()
        raw["StockCode"] = (ticker or "UNKNOWN").upper()

    tickers = sorted(raw["StockCode"].astype(str).str.upper().unique())
    universe_total = len(tickers)
    skipped_due_to_cap = 0
    unavailable_count = 0
    if ticker:
        tickers = [ticker.upper()]
    elif len(tickers) > max_universe:
        # Explicit cap — never silent. Meta reports skipped_due_to_cap.
        skipped_due_to_cap = len(tickers) - max_universe
        tickers = tickers[:max_universe]

    scanned = 0
    for code in tickers:
        scanned += 1
        g = raw[raw["StockCode"].astype(str).str.upper() == code].copy()
        if date:
            g = g[pd.to_datetime(g["Date"], errors="coerce") <= pd.Timestamp(date)]
        if len(g) == 0:
            unavailable_count += 1
            continue
        enriched = enrich_structure(g)
        if len(enriched) == 0:
            continue
        company = None
        if code in meta_map:
            company = meta_map[code].get("name") or meta_map[code].get("StockName")

        if tf == "close_pressure":
            row = evaluate_close_pressure_row(enriched, company=company, now_jakarta=now_jakarta)
        elif tf == "swing":
            row = evaluate_swing_row(enriched, company=company)
        else:
            row = evaluate_long_term_candidate(
                ticker=code,
                company_meta=meta_map.get(code),
                enriched=enriched,
            )

        if setup and row.get("setup") != setup:
            continue
        if signal and str(row.get("signal") or "").lower() != str(signal).lower():
            continue
        if not include_not_qualified and row.get("setup") == SETUP_NOT_QUALIFIED:
            # Still allow long-term PARTIAL candidates marked differently
            if tf != "long_term":
                continue
            if row.get("status") == STATUS_INSUFFICIENT_DATA:
                continue

        results.append(row)

    # Sort: qualified / higher engine_score first; nulls last.
    def _sort_key(r: dict[str, Any]) -> tuple:
        qual = 0 if r.get("setup") != SETUP_NOT_QUALIFIED else 1
        score = r.get("engine_score")
        score_v = -float(score) if isinstance(score, (int, float)) else 0.0
        return (qual, score_v, r.get("ticker") or "")

    results.sort(key=_sort_key)
    page = results[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < len(results) else None

    return {
        "results": page,
        "meta": {
            "status": "ok" if page else STATUS_UNAVAILABLE,
            "timeframe": tf,
            "as_of": date or (page[0].get("as_of") if page else None),
            "count": len(page),
            "total_matched": len(results),
            "limit": limit,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "universe_total": universe_total,
            "universe_scanned": scanned,
            "universe_capped": skipped_due_to_cap > 0,
            "skipped_due_to_cap": skipped_due_to_cap,
            "unavailable_count": unavailable_count,
            "returned": len(page),
            "max_universe": max_universe,
            "network_alpha_required": False,
            "engine_version": ENGINE_VERSION,
            "min_rr": MIN_RR,
            "min_opportunity_pct_close_pressure": MIN_OPPORTUNITY_PCT,
            "production_eligibility": PRODUCTION_ELIGIBILITY_STATUS,
            "production_eligibility_reason": PRODUCTION_ELIGIBILITY_REASON,
            "limitations": limitations,
            "calculated_at": datetime.now(UTC).isoformat(),
        },
    }
