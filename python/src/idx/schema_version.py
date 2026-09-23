"""DATA_SCHEMA_VERSION + legacy/current/unsupported handling."""

from __future__ import annotations

from typing import Any

DATA_SCHEMA_VERSION = "1.0.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0.0", "0.9.0"})
LEGACY_ALIASES = {
    "pbv": "price_bv",
    "price": "close",
    "market_cap": "estimated_mcap",
}


def schema_meta() -> dict[str, Any]:
    return {
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "supported": sorted(SUPPORTED_SCHEMA_VERSIONS),
        "legacy_aliases": dict(LEGACY_ALIASES),
    }


def classify_schema_version(version: str | None) -> str:
    if version is None or version == "":
        return "legacy"
    if version == DATA_SCHEMA_VERSION:
        return "current"
    if version in SUPPORTED_SCHEMA_VERSIONS:
        return "legacy"
    return "unsupported"


def normalize_company_record(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Map legacy aliases → canonical fields; never invent numeric zeros."""
    if not isinstance(raw, dict):
        return {
            "code": None,
            "name": None,
            "schema_version": DATA_SCHEMA_VERSION,
            "schema_status": "legacy",
        }
    out = dict(raw)
    for legacy, canonical in LEGACY_ALIASES.items():
        if out.get(canonical) is None and legacy in out:
            out[canonical] = out.get(legacy)
    code = out.get("code") or out.get("StockCode") or out.get("ticker")
    out["code"] = str(code).upper().strip() if code else None
    if out.get("name") is None:
        out["name"] = out.get("StockName") or out.get("NamaEmiten")
    ver = out.get("schema_version") or out.get("DATA_SCHEMA_VERSION")
    status = classify_schema_version(str(ver) if ver is not None else None)
    out["schema_version"] = DATA_SCHEMA_VERSION if status != "unsupported" else ver
    out["schema_status"] = status
    return out


def attach_schema(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["DATA_SCHEMA_VERSION"] = DATA_SCHEMA_VERSION
    return out
