"""
USD/IDR exchange rate resolution with explicit source lineage.

Commercial path rule (DECISION_LOG): Yahoo/yfinance must NOT be a hidden
production dependency. Live Yahoo and open.er-api fetches are opt-in only.

Resolution order:
  1. Fresh local cache (data/usd_idr_rate.json)
  2. Live providers only when explicitly allowed via env flags
  3. Stale cache
  4. DEFAULT_USD_IDR_RATE constant (labeled — NOT a market quote)

Env flags:
  RITELINSIGHT_ALLOW_YAHOO_FX=1      — permit yfinance/Yahoo USDIDR=X
  RITELINSIGHT_ALLOW_OPEN_ER_API=1   — permit open.er-api.com
  RITELINSIGHT_ENV=production        — does not auto-enable live FX

Quote ``status`` values (mutually exclusive intent):
  live | cached | stale_cache | default_constant | unavailable
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Literal

from idx.core.utils import DATA_DIR, get_logger

log = get_logger("idx.core.currency")

CACHE_FILE = os.path.join(DATA_DIR, "usd_idr_rate.json")
DEFAULT_USD_IDR_RATE = 16200.0
DEFAULT_CACHE_TTL_SECONDS = 86400  # 24 hours
ENGINE_VERSION = "fx-1.2"

FxStatus = Literal["live", "cached", "stale_cache", "default_constant", "unavailable"]

_LIVE_ORIGINS = frozenset({"yfinance_yahoo", "open_er_api"})


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def yahoo_fx_allowed() -> bool:
    return _env_truthy("RITELINSIGHT_ALLOW_YAHOO_FX")


def open_er_api_allowed() -> bool:
    return _env_truthy("RITELINSIGHT_ALLOW_OPEN_ER_API")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_origin(raw: str | None) -> str:
    if not raw:
        return "unknown"
    src = str(raw)
    if src.startswith("stale_cache:"):
        return src.split(":", 1)[1] or "unknown"
    if src == "live_fetch":
        return "unknown_live"
    return src


def _license_for(origin: str, status: FxStatus) -> str:
    if status == "default_constant":
        return "N/A_CONSTANT_NOT_A_MARKET_QUOTE"
    if status == "unavailable":
        return "N/A"
    origin_n = _normalize_origin(origin)
    if origin_n in _LIVE_ORIGINS or origin_n == "unknown_live":
        return "LICENSE_REVIEW_REQUIRED"
    return "LOCAL_CACHE"


def _quote(
    rate: float | None,
    *,
    status: FxStatus,
    origin: str,
    quality: str,
    live_attempted: bool,
    notes: str = "",
    confidence: float | None = None,
    cache_age_hours: float | None = None,
) -> dict[str, Any]:
    """Build lineage payload. default_constant is never a market quote."""
    is_live = status == "live"
    is_market_quote = status in ("live", "cached", "stale_cache") and rate is not None
    # Stale/cached numbers may originate from a prior live fetch, but they are
    # NOT current live quotes — consumers must use ``status`` / ``is_live``.
    return {
        "rate": None if rate is None else float(rate),
        "status": status,
        "source": status if status in ("default_constant", "unavailable") else (
            f"{status}:{_normalize_origin(origin)}" if status in ("cached", "stale_cache") else origin
        ),
        "origin": _normalize_origin(origin),
        "quality": quality,
        "confidence": confidence,
        "is_live": is_live,
        "is_market_quote": is_market_quote,
        "is_default_constant": status == "default_constant",
        "is_verified_fx": False,  # never claim verified without contracted FX provider
        "live_attempted": live_attempted,
        "yahoo_allowed": yahoo_fx_allowed(),
        "open_er_api_allowed": open_er_api_allowed(),
        "license_status": _license_for(origin, status),
        "cache_age_hours": cache_age_hours,
        "notes": notes,
        "as_of": _utc(),
        "engine_version": ENGINE_VERSION,
        "calculated_at": _utc(),
    }


def _load_cached_rate() -> dict[str, Any] | None:
    """Loads rate from cache file if valid."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "rate" in data and "timestamp" in data:
                return data
    except Exception as exc:
        log.warning("Failed to read exchange rate cache: %s", exc)
    return None


def _save_cached_rate(rate: float, origin: str) -> None:
    """Persists rate to local JSON cache with lineage."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        payload = {
            "rate": float(rate),
            "timestamp": time.time(),
            "source": origin,
            "origin": origin,
            "as_of": _utc(),
            "engine_version": ENGINE_VERSION,
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as exc:
        log.warning("Failed to write exchange rate cache: %s", exc)


def fetch_live_usd_idr_rate() -> float | None:
    """Legacy helper: float if an *allowed* live provider succeeds."""
    quote = _fetch_live_quote()
    if quote is None or quote.get("rate") is None:
        return None
    return float(quote["rate"])


def _fetch_live_quote() -> dict[str, Any] | None:
    """Attempt allowed live FX providers. Never calls Yahoo unless opted in."""
    if yahoo_fx_allowed():
        try:
            import yfinance as yf

            ticker = yf.Ticker("USDIDR=X")
            fast_info = getattr(ticker, "fast_info", None)
            if fast_info and getattr(fast_info, "last_price", None):
                price = float(fast_info.last_price)
                if 10000.0 <= price <= 30000.0:
                    log.info(
                        "Fetched USD/IDR from Yahoo Finance fast_info: %.2f (opt-in)",
                        price,
                    )
                    return _quote(
                        price,
                        status="live",
                        origin="yfinance_yahoo",
                        quality="C",
                        live_attempted=True,
                        notes=(
                            "Opt-in Yahoo live FX — LICENSE_REVIEW_REQUIRED. "
                            "Not a contracted/verified commercial FX feed."
                        ),
                        confidence=0.6,
                    )

            hist = ticker.history(period="5d")
            if not hist.empty and "Close" in hist.columns:
                price = float(hist["Close"].iloc[-1])
                if 10000.0 <= price <= 30000.0:
                    log.info(
                        "Fetched USD/IDR from Yahoo Finance history: %.2f (opt-in)",
                        price,
                    )
                    return _quote(
                        price,
                        status="live",
                        origin="yfinance_yahoo",
                        quality="C",
                        live_attempted=True,
                        notes=(
                            "Opt-in Yahoo live FX (history) — LICENSE_REVIEW_REQUIRED. "
                            "Not a contracted/verified commercial FX feed."
                        ),
                        confidence=0.55,
                    )
        except Exception as exc:
            log.debug("Yahoo Finance rate fetch failed: %s", exc)
    else:
        log.debug("Yahoo FX skipped — RITELINSIGHT_ALLOW_YAHOO_FX not set")

    if open_er_api_allowed():
        try:
            import urllib.request

            url = "https://open.er-api.com/v6/latest/USD"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                rates = data.get("rates", {})
                if "IDR" in rates:
                    price = float(rates["IDR"])
                    if 10000.0 <= price <= 30000.0:
                        log.info(
                            "Fetched USD/IDR from open exchange API: %.2f (opt-in)",
                            price,
                        )
                        return _quote(
                            price,
                            status="live",
                            origin="open_er_api",
                            quality="C",
                            live_attempted=True,
                            notes=(
                                "Opt-in open.er-api live FX — LICENSE_REVIEW_REQUIRED. "
                                "Not a contracted/verified commercial FX feed."
                            ),
                            confidence=0.5,
                        )
        except Exception as exc:
            log.debug("Open exchange API fetch failed: %s", exc)
    else:
        log.debug("open.er-api FX skipped — RITELINSIGHT_ALLOW_OPEN_ER_API not set")

    return None


def resolve_usd_idr_quote(
    force_refresh: bool = False,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    default_rate: float = DEFAULT_USD_IDR_RATE,
    *,
    allow_default: bool = True,
) -> dict[str, Any]:
    """Resolve USD/IDR with explicit status / quality / license lineage.

    ``allow_default=False`` yields ``status=unavailable`` (rate=None) when no
    cache/live quote exists — never silently invents a market quote.
    """
    cached = _load_cached_rate()
    now = time.time()
    live_ok = yahoo_fx_allowed() or open_er_api_allowed()

    if not force_refresh and cached:
        age = now - float(cached.get("timestamp") or 0)
        if age < cache_ttl_seconds:
            rate = float(cached.get("rate", default_rate))
            origin = _normalize_origin(
                str(cached.get("origin") or cached.get("source") or "local_cache")
            )
            return _quote(
                rate,
                status="cached",
                origin=origin,
                quality="B",
                live_attempted=False,
                notes=(
                    f"Fresh local cache (age {age / 3600.0:.1f}h). "
                    "Cached value — not a live market quote."
                ),
                confidence=0.7,
                cache_age_hours=round(age / 3600.0, 3),
            )

    if force_refresh or not cached or (
        cached and (now - float(cached.get("timestamp") or 0)) >= cache_ttl_seconds
    ):
        if live_ok:
            live = _fetch_live_quote()
            if live is not None and live.get("rate") is not None:
                _save_cached_rate(float(live["rate"]), origin=str(live.get("origin") or live["source"]))
                return live
        elif force_refresh:
            log.info(
                "FX live refresh requested but no live provider allowed "
                "(set RITELINSIGHT_ALLOW_YAHOO_FX or RITELINSIGHT_ALLOW_OPEN_ER_API)"
            )

    if cached and "rate" in cached:
        age = now - float(cached.get("timestamp") or 0)
        stale_rate = float(cached["rate"])
        origin = _normalize_origin(
            str(cached.get("origin") or cached.get("source") or "stale_cache")
        )
        log.warning(
            "Using stale cached USD/IDR rate: %.2f (live providers not used or failed)",
            stale_rate,
        )
        return _quote(
            stale_rate,
            status="stale_cache",
            origin=origin,
            quality="C",
            live_attempted=live_ok,
            notes=(
                "Stale cache — not a live/current market quote. "
                "Configure licensed FX or refresh cache manually."
            ),
            confidence=0.4,
            cache_age_hours=round(age / 3600.0, 3),
        )

    if not allow_default:
        return _quote(
            None,
            status="unavailable",
            origin="none",
            quality="U",
            live_attempted=live_ok,
            notes=(
                "FX unavailable: no cache and no allowed live provider. "
                "Not substituting a default constant."
            ),
            confidence=None,
        )

    log.warning(
        "No USD/IDR rate available; using default constant %.2f "
        "(NOT a live/verified market quote)",
        default_rate,
    )
    return _quote(
        default_rate,
        status="default_constant",
        origin="default_constant",
        quality="CONSTANT",
        live_attempted=False,
        notes=(
            "DEFAULT CONSTANT — not a live FX quote, not a verified market rate, "
            "not a current market quote. FX live providers NOT_CONFIGURED unless "
            "RITELINSIGHT_ALLOW_YAHOO_FX / RITELINSIGHT_ALLOW_OPEN_ER_API are set. "
            "Use for IDR conversion scaffolding only; treat USD-derived metrics as low confidence."
        ),
        confidence=0.1,
    )


def get_usd_idr_rate(
    force_refresh: bool = False,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    default_rate: float = DEFAULT_USD_IDR_RATE,
) -> float:
    """Returns USD/IDR as float (may be default_constant). Prefer ``resolve_usd_idr_quote``."""
    q = resolve_usd_idr_quote(
        force_refresh=force_refresh,
        cache_ttl_seconds=cache_ttl_seconds,
        default_rate=default_rate,
        allow_default=True,
    )
    rate = q.get("rate")
    if rate is None:
        return float(default_rate)
    return float(rate)


def fx_status() -> dict[str, Any]:
    """Capability / configuration status for Data Center / integrations."""
    cached = _load_cached_rate()
    current = resolve_usd_idr_quote(force_refresh=False, allow_default=True)
    return {
        "provider": "fx_usd_idr",
        "status": (
            "PARTIAL"
            if cached or yahoo_fx_allowed() or open_er_api_allowed()
            else "NOT_CONFIGURED"
        ),
        "configured_live": yahoo_fx_allowed() or open_er_api_allowed(),
        "yahoo_allowed": yahoo_fx_allowed(),
        "open_er_api_allowed": open_er_api_allowed(),
        "cache_present": bool(cached),
        "cache_source": (cached or {}).get("source"),
        "default_constant": DEFAULT_USD_IDR_RATE,
        "current_quote": {
            "rate": current.get("rate"),
            "status": current.get("status"),
            "source": current.get("source"),
            "origin": current.get("origin"),
            "quality": current.get("quality"),
            "confidence": current.get("confidence"),
            "is_live": current.get("is_live"),
            "is_market_quote": current.get("is_market_quote"),
            "is_default_constant": current.get("is_default_constant"),
            "is_verified_fx": current.get("is_verified_fx"),
            "notes": current.get("notes"),
        },
        "hidden_yahoo_production_dependency": False,
        "license_notes": (
            "Yahoo/yfinance and open.er-api are opt-in only; commercial rights "
            "LICENSE_REVIEW_REQUIRED. Default constant is never a market quote. "
            "Prefer contracted FX for production USD conversions."
        ),
        "engine_version": ENGINE_VERSION,
        "calculated_at": _utc(),
    }
