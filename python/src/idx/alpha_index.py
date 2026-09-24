"""Alpha Index HTTP client (external data source — not local SoT).

Auth: HTTP Bearer via ``ALPHA_INDEX_API_KEY`` (never hardcode).
Base URL: ``ALPHA_INDEX_BASE_URL`` (default ``https://api.indexalpha.id``).

Endpoints used are taken from the public OpenAPI at ``/openapi.json``.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://api.indexalpha.id"
DEFAULT_TIMEOUT_SEC = 30.0
MAX_RETRIES = 1  # one retry only for transient 502/503/504

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,9}$")
_INVESTOR_RE = re.compile(r"^(all|f|or|d)$")
_MARKET_RE = re.compile(r"^(ALL|RG|NG)$")


class AlphaIndexError(Exception):
    """Safe client error (never includes Authorization / API key)."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _redact(text: str) -> str:
    """Strip bearer/api-key looking substrings from error text."""
    out = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text)
    out = re.sub(r"(?i)(api[_-]?key|authorization)[=:]\s*\S+", r"\1=***", out)
    return out


def get_base_url() -> str:
    return (os.environ.get("ALPHA_INDEX_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def get_api_key() -> str | None:
    key = os.environ.get("ALPHA_INDEX_API_KEY") or os.environ.get("INDEXALPHA_API_KEY")
    if key:
        key = key.strip()
        return key or None
    # Optional local .env (gitignored). Skip when explicitly disabled (unit tests).
    if os.environ.get("ALPHA_INDEX_SKIP_DOTENV", "").strip() in ("1", "true", "TRUE"):
        return None
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)
    except Exception:
        pass
    key = os.environ.get("ALPHA_INDEX_API_KEY") or os.environ.get("INDEXALPHA_API_KEY")
    if key is None:
        return None
    key = key.strip()
    return key or None


def auth_configured() -> bool:
    return bool(get_api_key())


def _validate_date(name: str, value: str) -> str:
    v = str(value).strip()
    if not _DATE_RE.match(v):
        raise AlphaIndexError(f"Invalid {name}: expected YYYY-MM-DD")
    return v


def _validate_ticker(ticker: str) -> str:
    t = str(ticker).strip().upper()
    if not _TICKER_RE.match(t):
        raise AlphaIndexError("Invalid ticker: expected 1–10 alphanumeric ticker")
    return t


def _auth_headers() -> dict[str, str]:
    key = get_api_key()
    if not key:
        raise AlphaIndexError(
            "ALPHA_INDEX_API_KEY not configured — set env or .env (never hardcode)",
            status=401,
        )
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "idx-bei-alpha-index-client/1.0",
    }


def _request_json(
    method: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    base = get_base_url()
    url = f"{base}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    headers = _auth_headers()
    attempt = 0
    while True:
        attempt += 1
        req = urllib.request.Request(url, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body = ""
            body = _redact(body)
            if status in (502, 503, 504) and attempt <= MAX_RETRIES + 1:
                continue
            raise AlphaIndexError(
                f"Alpha Index HTTP {status} for {path}"
                + (f": {body}" if body else ""),
                status=status,
            ) from None
        except urllib.error.URLError as exc:
            raise AlphaIndexError(
                f"Alpha Index network error for {path}: {_redact(str(exc.reason))}"
            ) from None

        if not raw:
            raise AlphaIndexError(f"Empty response from {path}", status=status)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AlphaIndexError(
                f"Invalid JSON from {path}: {_redact(str(exc))}", status=status
            ) from None
        if not isinstance(parsed, dict):
            raise AlphaIndexError(f"Unexpected JSON type from {path}", status=status)
        return parsed


def _compact_envelope(payload: dict[str, Any], *, limit: int | None = None) -> dict[str, Any]:
    """Return machine-readable summary without dumping huge payloads blindly."""
    success = bool(payload.get("success", True))
    err = payload.get("error")
    data = payload.get("data")
    out: dict[str, Any] = {
        "success": success,
        "source": "alpha_index",
        "base_url": get_base_url(),
        "error": err,
    }
    if isinstance(data, list):
        rows = data
        if limit is not None and limit >= 0:
            rows = data[:limit]
        out["count"] = len(data)
        out["returned"] = len(rows)
        out["data"] = rows
        if limit is not None and len(data) > len(rows):
            out["truncated"] = True
    elif data is None:
        out["data"] = None
        out["count"] = 0
    else:
        out["data"] = data
    return out


def broker_summary(
    *,
    ticker: str,
    date_from: str,
    date_to: str,
    investor: str = "all",
    market: str = "RG",
    row_limit: int = 50,
) -> dict[str, Any]:
    """GET /stocks/broker-summary (OpenAPI)."""
    inv = str(investor).strip().lower()
    mkt = str(market).strip().upper()
    if not _INVESTOR_RE.match(inv):
        raise AlphaIndexError("Invalid investor: use all|f|d|or")
    if not _MARKET_RE.match(mkt):
        raise AlphaIndexError("Invalid market: use RG|NG|ALL")
    payload = _request_json(
        "GET",
        "/stocks/broker-summary",
        query={
            "ticker": _validate_ticker(ticker),
            "from": _validate_date("from", date_from),
            "to": _validate_date("to", date_to),
            "investor": inv,
            "market": mkt,
        },
    )
    out = _compact_envelope(payload, limit=max(0, int(row_limit)))
    out["endpoint"] = "/stocks/broker-summary"
    out["params"] = {
        "ticker": _validate_ticker(ticker),
        "from": date_from,
        "to": date_to,
        "investor": inv,
        "market": mkt,
    }
    return out


def stock_ohlcv(
    *,
    ticker: str,
    date_from: str,
    date_to: str,
    row_limit: int = 120,
) -> dict[str, Any]:
    """GET /stocks/ohlcv — daily OHLCV (unadjusted)."""
    payload = _request_json(
        "GET",
        "/stocks/ohlcv",
        query={
            "ticker": _validate_ticker(ticker),
            "from": _validate_date("from", date_from),
            "to": _validate_date("to", date_to),
        },
    )
    out = _compact_envelope(payload, limit=max(0, int(row_limit)))
    out["endpoint"] = "/stocks/ohlcv"
    out["params"] = {
        "ticker": _validate_ticker(ticker),
        "from": date_from,
        "to": date_to,
    }
    out["note"] = "Prices/volume as-traded (unadjusted); missing dates omitted."
    return out


def foreign_flow(
    *,
    ticker: str,
    date_from: str,
    date_to: str,
    market: str = "ALL",
) -> dict[str, Any]:
    """GET /foreign-flow (OpenAPI)."""
    mkt = str(market).strip().upper()
    if not _MARKET_RE.match(mkt):
        raise AlphaIndexError("Invalid market: use RG|NG|ALL")
    payload = _request_json(
        "GET",
        "/foreign-flow",
        query={
            "ticker": _validate_ticker(ticker),
            "from": _validate_date("from", date_from),
            "to": _validate_date("to", date_to),
            "market": mkt,
        },
    )
    out = _compact_envelope(payload)
    out["endpoint"] = "/foreign-flow"
    out["params"] = {
        "ticker": _validate_ticker(ticker),
        "from": date_from,
        "to": date_to,
        "market": mkt,
    }
    return out
