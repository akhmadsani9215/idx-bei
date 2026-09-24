"""Private watchlist store — subject-scoped, never trusts client user_id."""

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
_STORE_PATH = os.path.join(DATA_DIR, ".ritelinsight_watchlists.json")
ENGINE_VERSION = "watchlist-1.0"


def _utc() -> str:
    return datetime.now(UTC).isoformat()


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


def _empty_item(ticker: str, **fields: Any) -> dict[str, Any]:
    return {
        "ticker": ticker.upper().strip(),
        "company": fields.get("company"),
        "group": fields.get("group") or "default",
        "notes": fields.get("notes"),
        "tags": fields.get("tags") or [],
        "priority": fields.get("priority"),
        "setup": fields.get("setup"),
        "current_price": fields.get("current_price"),
        "score": fields.get("score"),
        "signal": fields.get("signal"),
        "entry": fields.get("entry"),
        "tp": fields.get("tp"),
        "cl": fields.get("cl"),
        "rr": fields.get("rr"),
        "alerts_status": fields.get("alerts_status") or "NONE",
        "added_at": fields.get("added_at") or _utc(),
        "updated_at": _utc(),
    }


def list_items(principal: SessionPrincipal) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        items = list(data.get("subjects", {}).get(principal.subject, {}).get("items", []))
    return {
        "items": items,
        "count": len(items),
        "auth_status": "NOT_CONFIGURED",
        "ownership": "session_subject",
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "as_of": _utc(),
    }


def add_item(principal: SessionPrincipal, payload: dict[str, Any]) -> dict[str, Any]:
    ticker = str(payload.get("ticker") or payload.get("code") or "").upper().strip()
    if not ticker or len(ticker) > 10:
        raise ValueError("ticker is required")
    with _LOCK:
        data = _load()
        subj = data.setdefault("subjects", {}).setdefault(principal.subject, {"items": []})
        items: list[dict[str, Any]] = subj["items"]
        for it in items:
            if it.get("ticker") == ticker:
                raise ValueError(f"duplicate ticker {ticker}")
        item = _empty_item(
            ticker,
            company=payload.get("company"),
            group=payload.get("group"),
            notes=payload.get("notes"),
            tags=payload.get("tags"),
            priority=payload.get("priority"),
            setup=payload.get("setup"),
            current_price=payload.get("current_price"),
            score=payload.get("score"),
            signal=payload.get("signal"),
            entry=payload.get("entry"),
            tp=payload.get("tp"),
            cl=payload.get("cl"),
            rr=payload.get("rr"),
            alerts_status=payload.get("alerts_status"),
        )
        items.insert(0, item)
        _save(data)
    return {"item": item, "status": "ok"}


def update_item(principal: SessionPrincipal, ticker: str, patch: dict[str, Any]) -> dict[str, Any]:
    code = ticker.upper().strip()
    allowed = {
        "company",
        "group",
        "notes",
        "tags",
        "priority",
        "setup",
        "current_price",
        "score",
        "signal",
        "entry",
        "tp",
        "cl",
        "rr",
        "alerts_status",
    }
    with _LOCK:
        data = _load()
        subj = data.get("subjects", {}).get(principal.subject)
        if not subj:
            raise KeyError(code)
        for it in subj["items"]:
            if it.get("ticker") == code:
                for k, v in patch.items():
                    if k in allowed:
                        it[k] = v
                it["updated_at"] = _utc()
                _save(data)
                return {"item": it, "status": "ok"}
        raise KeyError(code)


def remove_item(principal: SessionPrincipal, ticker: str) -> dict[str, Any]:
    code = ticker.upper().strip()
    with _LOCK:
        data = _load()
        subj = data.get("subjects", {}).get(principal.subject)
        if not subj:
            raise KeyError(code)
        before = len(subj["items"])
        subj["items"] = [it for it in subj["items"] if it.get("ticker") != code]
        if len(subj["items"]) == before:
            raise KeyError(code)
        _save(data)
    return {"status": "ok", "removed": code}


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
