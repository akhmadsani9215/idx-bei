"""Operational status surface for Data Center / readiness probes.

No secrets in logs or response payloads.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from idx.auth_session import auth_status
from idx.cors_config import resolve_cors_origins
from idx.providers import integrations_overview
from idx.schema_version import DATA_SCHEMA_VERSION


ENGINE_VERSION = "ops-1.0"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_mode() -> str:
    return (os.environ.get("RITELINSIGHT_ENV") or "development").strip().lower()


def readiness() -> dict[str, Any]:
    """Process-ready probe: app can serve; external providers may still be absent."""
    cors = resolve_cors_origins()
    mode = _env_mode()
    ready = True
    blockers: list[str] = []
    if mode in ("prod", "production") and not cors.get("allow_origins"):
        ready = False
        blockers.append("RITELINSIGHT_CORS_ORIGINS empty in production")
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "blockers": blockers,
        "env": mode,
        "schema_version": DATA_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "calculated_at": _utc(),
    }


def ops_status() -> dict[str, Any]:
    """Aggregated operational view — safe for Data Center UI."""
    from idx.ingestion import INTEGRATION_STATUS, get_full_ingestion_status

    try:
        ingestion = get_full_ingestion_status()
    except Exception:
        ingestion = {"status": "error", "message": "ingestion status unavailable"}

    integrations = integrations_overview()
    auth = auth_status()
    cors = resolve_cors_origins()
    mode = _env_mode()

    # Memory / process hints — bounded, no PII
    mem_warning = None
    try:
        import resource  # type: ignore

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux: KB; macOS: bytes — report raw with unit note
        mem_warning = {"ru_maxrss": usage, "unit": "platform_dependent"}
    except Exception:
        mem_warning = None

    return {
        "env": mode,
        "ready": readiness(),
        "schema_version": DATA_SCHEMA_VERSION,
        "auth": {
            "status": auth.get("status"),
            "mode": auth.get("mode"),
            "multi_user_identity_provider": auth.get("multi_user_identity_provider"),
        },
        "cors": {
            "mode": cors.get("mode"),
            "origins_configured": bool(cors.get("allow_origins")),
            "allow_credentials": cors.get("allow_credentials"),
            "warning": cors.get("warning"),
        },
        "integrations": {
            "realtime": integrations.get("realtime"),
            "ai": (integrations.get("ai") or {}).get("status"),
            "notifications": (integrations.get("notifications") or {}).get("status"),
            "payment": (integrations.get("payment") or {}).get("status"),
            "market_data": (integrations.get("market_data") or {}).get("status"),
        },
        "integration_flags": dict(INTEGRATION_STATUS),
        "provider_state": {
            "realtime_connection": "NOT_CONFIGURED",
            "stale_data": None,
            "cache_status": "local_files",
        },
        "ingestion_summary": {
            "status": ingestion.get("status") if isinstance(ingestion, dict) else None,
            "keys": sorted(ingestion.keys())[:40] if isinstance(ingestion, dict) else [],
        },
        "memory": mem_warning,
        "engine_version": ENGINE_VERSION,
        "calculated_at": _utc(),
        "notes": (
            "External realtime/IdP/AI/Telegram/Payment remain NOT_CONFIGURED "
            "until product-owner contracts are in place. No secrets in this payload."
        ),
    }
