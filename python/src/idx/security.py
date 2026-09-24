"""HTTP security baseline: operator authorization, rate limiting, security headers.

Configuration is environment-only; nothing here invents credentials or providers.

* ``RITELINSIGHT_ADMIN_TOKEN`` — operator token for state-changing system routes
  (ingestion trigger, WS broadcast). Unset in production → routes fail closed (503).
* ``RITELINSIGHT_RATE_LIMIT_ENABLED`` — force limiter on/off (default: on in production).
* ``RITELINSIGHT_RATE_LIMIT_PER_MIN`` / ``RITELINSIGHT_RATE_LIMIT_HEAVY_PER_MIN``.
* ``RITELINSIGHT_TRUST_PROXY=1`` — use the first ``X-Forwarded-For`` hop as client IP
  (only behind a trusted reverse proxy that overwrites the header).
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import deque
from typing import Any

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

DEFAULT_RATE_PER_MIN = 240
DEFAULT_HEAVY_RATE_PER_MIN = 12
HEAVY_PATHS: frozenset[str] = frozenset(
    {
        "/api/backtest",
        "/api/strategy/run",
        "/api/strategy/validate",
        "/api/system/trigger-ingestion",
        "/api/query/sql",
    }
)
EXEMPT_PREFIXES: tuple[str, ...] = ("/health", "/ready", "/assets", "/dashboard")
_MAX_TRACKED_KEYS = 10_000

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
HSTS_VALUE = "max-age=31536000; includeSubDomains"


def is_production() -> bool:
    return (os.environ.get("RITELINSIGHT_ENV") or "").strip().lower() in ("prod", "production")


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def rate_limit_enabled() -> bool:
    flag = (os.environ.get("RITELINSIGHT_RATE_LIMIT_ENABLED") or "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    return is_production()


def require_operator(
    x_ritel_admin_token: str | None = Header(default=None, alias="X-Ritel-Admin-Token"),
) -> None:
    """Dependency for state-changing system routes."""
    expected = os.environ.get("RITELINSIGHT_ADMIN_TOKEN") or ""
    if not expected:
        if is_production():
            raise HTTPException(
                status_code=503,
                detail="NOT_CONFIGURED: operator token (RITELINSIGHT_ADMIN_TOKEN) not set",
            )
        return
    if not x_ritel_admin_token or not hmac.compare_digest(x_ritel_admin_token, expected):
        raise HTTPException(status_code=401, detail="Operator token required")


class SlidingWindowLimiter:
    """In-process per-key sliding window (single worker; use a shared store when scaling out)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float = 60.0) -> float | None:
        """Record a request; return retry-after seconds when over ``limit``."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > _MAX_TRACKED_KEYS:
                self._hits = {k: q for k, q in self._hits.items() if q and now - q[-1] < window_s}
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= window_s:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, window_s - (now - q[0]))
            q.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


LIMITER = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    if (os.environ.get("RITELINSIGHT_TRUST_PROXY") or "") == "1":
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def install_security_middleware(app) -> None:
    @app.middleware("http")
    async def _security_middleware(request: Request, call_next):
        path = request.url.path
        if rate_limit_enabled() and not path.startswith(EXEMPT_PREFIXES):
            heavy = path in HEAVY_PATHS
            limit = (
                _env_int("RITELINSIGHT_RATE_LIMIT_HEAVY_PER_MIN", DEFAULT_HEAVY_RATE_PER_MIN)
                if heavy
                else _env_int("RITELINSIGHT_RATE_LIMIT_PER_MIN", DEFAULT_RATE_PER_MIN)
            )
            bucket = "heavy" if heavy else "general"
            retry = LIMITER.hit(f"{client_ip(request)}|{bucket}", limit)
            if retry is not None:
                response = JSONResponse(
                    status_code=429,
                    content={
                        "error": "RATE_LIMITED",
                        "detail": "Too many requests",
                        "bucket": bucket,
                    },
                    headers={"Retry-After": str(int(retry))},
                )
                _apply_headers(response)
                return response
        response = await call_next(request)
        _apply_headers(response)
        return response


def _apply_headers(response) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if is_production():
        response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)


def security_status() -> dict[str, Any]:
    return {
        "production": is_production(),
        "operator_token": "CONFIGURED"
        if os.environ.get("RITELINSIGHT_ADMIN_TOKEN")
        else "NOT_CONFIGURED",
        "rate_limit": {
            "enabled": rate_limit_enabled(),
            "per_min": _env_int("RITELINSIGHT_RATE_LIMIT_PER_MIN", DEFAULT_RATE_PER_MIN),
            "heavy_per_min": _env_int(
                "RITELINSIGHT_RATE_LIMIT_HEAVY_PER_MIN", DEFAULT_HEAVY_RATE_PER_MIN
            ),
            "scope": "in-process (single worker)",
        },
        "security_headers": sorted(SECURITY_HEADERS)
        + (["Strict-Transport-Security"] if is_production() else []),
        "content_security_policy": "NOT_CONFIGURED — SPA inline/runtime needs audit in UI finalization",
        "tls": "EXTERNAL — terminate at reverse proxy/hosting (not configured in repo)",
        "idp": "NOT_CONFIGURED — opaque local sessions only",
    }
