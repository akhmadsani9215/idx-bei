"""Trading Plan & Journal — Excel V1 semantics (Confirm Score / Result Auto / P/L)."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from typing import Any

from idx.auth_session import SessionPrincipal
from idx.core.utils import DATA_DIR
from idx.schema_version import DATA_SCHEMA_VERSION

_LOCK = threading.Lock()
_STORE_PATH = os.path.join(DATA_DIR, ".ritelinsight_trading_journal.json")
ENGINE_VERSION = "trading-plan-1.0"

DEFAULT_FEE_BUY = 0.0015
DEFAULT_FEE_SELL = 0.0025
LOT_SIZE = 100

_POS = {"BULLISH", "BUY", "OK", "ACC"}
_NEG = {"BEARISH", "SELL", "NOK", "DIST"}
_ZERO = {"SIDEWAY", "NORMAL", "", None}


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def confirmation_point(value: Any) -> int:
    v = _norm(value)
    if v in _POS:
        return 1
    if v in _NEG:
        return -1
    return 0


def compute_confirm_score(plan: dict[str, Any]) -> int:
    keys = (
        "tf_1d",
        "tf_15m",
        "tf_5m",
        "macd_bias",
        "volume_bias",
        "supertrend_bias",
        "ma5_ok",
        "ma20_ok",
        "ma50_ok",
        "vwap_ok",
        "broksum",
    )
    return int(sum(confirmation_point(plan.get(k)) for k in keys))


def compute_result_auto(plan: dict[str, Any], score: int | None = None) -> str:
    """Preserve Excel Result (Auto) exactly."""
    s = compute_confirm_score(plan) if score is None else int(score)
    if _norm(plan.get("tf_1d")) == "BEARISH":
        return "No Trade"
    if _norm(plan.get("volume_bias")) == "SELL" and _norm(plan.get("supertrend_bias")) == "SELL":
        return "No Trade"
    if _norm(plan.get("broksum")) == "DIST":
        return "No Trade"
    if s >= 6:
        return "Buy"
    if s >= 2:
        return "Wait & See"
    return "No Trade"


def compute_rr(entry: Any, tp: Any, cl: Any) -> float | None:
    try:
        e = float(entry)
        t = float(tp)
        c = float(cl)
    except (TypeError, ValueError):
        return None
    den = e - c
    if den == 0:
        return None
    return (t - e) / den


def compute_journal_pl(
    *,
    entry_price: Any,
    exit_price: Any,
    lots: Any,
    stop_price: Any = None,
    fee_buy_pct: float = DEFAULT_FEE_BUY,
    fee_sell_pct: float = DEFAULT_FEE_SELL,
) -> dict[str, Any]:
    try:
        entry = float(entry_price)
        exit_ = float(exit_price)
        lot_n = float(lots)
    except (TypeError, ValueError):
        return {
            "buy_value": None,
            "sell_value": None,
            "fee_buy": None,
            "fee_sell": None,
            "gross_pl_per_share": None,
            "net_pl": None,
            "net_pl_pct": None,
            "rr_realized": None,
            "shares": None,
        }
    shares = lot_n * LOT_SIZE
    buy_value = entry * shares
    sell_value = exit_ * shares
    fee_buy = buy_value * fee_buy_pct
    fee_sell = sell_value * fee_sell_pct
    net_pl = (sell_value - fee_sell) - (buy_value + fee_buy)
    net_pl_pct = net_pl / (buy_value + fee_buy) if (buy_value + fee_buy) else None
    rr_realized = None
    try:
        if stop_price is not None:
            rr_realized = compute_rr(entry, exit_, float(stop_price))
    except (TypeError, ValueError):
        rr_realized = None
    return {
        "buy_value": buy_value,
        "sell_value": sell_value,
        "fee_buy": fee_buy,
        "fee_sell": fee_sell,
        "gross_pl_per_share": exit_ - entry,
        "net_pl": net_pl,
        "net_pl_pct": net_pl_pct,
        "rr_realized": rr_realized,
        "shares": shares,
    }


def enrich_plan(plan: dict[str, Any]) -> dict[str, Any]:
    out = dict(plan)
    score = compute_confirm_score(out)
    out["confirm_score"] = score
    out["result_auto"] = compute_result_auto(out, score)
    out["rr_planned"] = compute_rr(out.get("entry_price"), out.get("tp"), out.get("cl"))
    # Optional web extensions — do not remove Excel single CL/TP semantics.
    out.setdefault("entry_zone", out.get("entry_price"))
    out.setdefault("tp1", out.get("tp"))
    out.setdefault("cl1", out.get("cl"))
    out["engine_version"] = ENGINE_VERSION
    out["DATA_SCHEMA_VERSION"] = DATA_SCHEMA_VERSION
    out["calculated_at"] = _utc()
    return out


def enrich_journal(
    entry: dict[str, Any],
    *,
    fee_buy_pct: float = DEFAULT_FEE_BUY,
    fee_sell_pct: float = DEFAULT_FEE_SELL,
) -> dict[str, Any]:
    out = dict(entry)
    pl = compute_journal_pl(
        entry_price=out.get("entry_price"),
        exit_price=out.get("exit_price"),
        lots=out.get("lots"),
        stop_price=out.get("stop_price"),
        fee_buy_pct=fee_buy_pct,
        fee_sell_pct=fee_sell_pct,
    )
    out.update(pl)
    out["engine_version"] = ENGINE_VERSION
    out["DATA_SCHEMA_VERSION"] = DATA_SCHEMA_VERSION
    out["calculated_at"] = _utc()
    return out


def weekly_recap(journals: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate by exit_date presence; empty-safe."""
    rows = [enrich_journal(j) for j in journals if isinstance(j, dict)]
    with_exit = [r for r in rows if r.get("exit_price") is not None and r.get("net_pl") is not None]
    wins = [r for r in with_exit if (r.get("net_pl") or 0) > 0]
    losses = [r for r in with_exit if (r.get("net_pl") or 0) < 0]
    total_net = sum(float(r["net_pl"]) for r in with_exit) if with_exit else None
    return {
        "total_trades": len(with_exit),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (100.0 * len(wins) / len(with_exit)) if with_exit else None,
        "total_pl_net": total_net,
        "avg_pl_net_pct": (
            sum(float(r["net_pl_pct"]) for r in with_exit if r.get("net_pl_pct") is not None)
            / len(with_exit)
            if with_exit
            else None
        ),
        "sample_status": "OK" if with_exit else "EMPTY",
        "engine_version": ENGINE_VERSION,
        "calculated_at": _utc(),
    }


def _load() -> dict[str, Any]:
    if not os.path.isfile(_STORE_PATH):
        return {"subjects": {}}
    try:
        with open(_STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"subjects": {}}
        data.setdefault("subjects", {})
        return data
    except (OSError, json.JSONDecodeError):
        return {"subjects": {}}


def _save(data: dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _STORE_PATH)


def list_plans(principal: SessionPrincipal) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
        items = data.get("subjects", {}).get(principal.subject, {}).get("plans", [])
        return [enrich_plan(p) for p in items]


def upsert_plan(principal: SessionPrincipal, plan: dict[str, Any]) -> dict[str, Any]:
    enriched = enrich_plan(plan)
    plan_id = str(enriched.get("id") or f"plan_{int(datetime.now(UTC).timestamp() * 1000)}")
    enriched["id"] = plan_id
    with _LOCK:
        data = _load()
        subj = data.setdefault("subjects", {}).setdefault(
            principal.subject, {"plans": [], "journals": []}
        )
        plans = subj["plans"]
        for i, p in enumerate(plans):
            if p.get("id") == plan_id:
                plans[i] = enriched
                _save(data)
                return enriched
        plans.insert(0, enriched)
        _save(data)
    return enriched


def list_journals(principal: SessionPrincipal) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
        items = data.get("subjects", {}).get(principal.subject, {}).get("journals", [])
        return [enrich_journal(j) for j in items]


def upsert_journal(principal: SessionPrincipal, entry: dict[str, Any]) -> dict[str, Any]:
    enriched = enrich_journal(entry)
    jid = str(enriched.get("id") or f"jrn_{int(datetime.now(UTC).timestamp() * 1000)}")
    enriched["id"] = jid
    with _LOCK:
        data = _load()
        subj = data.setdefault("subjects", {}).setdefault(
            principal.subject, {"plans": [], "journals": []}
        )
        rows = subj["journals"]
        for i, j in enumerate(rows):
            if j.get("id") == jid:
                rows[i] = enriched
                _save(data)
                return enriched
        rows.insert(0, enriched)
        _save(data)
    return enriched


def reset_store_for_tests(path: str | None = None) -> None:
    global _STORE_PATH
    if path:
        _STORE_PATH = path
    with _LOCK:
        if os.path.isfile(_STORE_PATH):
            try:
                os.remove(_STORE_PATH)
            except OSError:
                pass
