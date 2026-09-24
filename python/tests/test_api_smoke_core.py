"""Cluster 15 — core API smoke: status codes + strict JSON (no NaN/Infinity) + honesty flags."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from idx.api import app

CORE_GET_ROUTES = (
    "/health",
    "/ready",
    "/api/schema",
    "/api/data-status",
    "/api/ops/status",
    "/api/integrations",
    "/api/realtime/status",
    "/api/strategy",
    "/api/strategy/research",
    "/api/big-money",
)


def _strict(text: str):
    def _reject(token):
        raise ValueError(f"non-finite JSON token {token}")

    return json.loads(text, parse_constant=_reject)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.mark.parametrize("route", CORE_GET_ROUTES)
def test_core_routes_return_strict_json(client, route):
    r = client.get(route)
    assert r.status_code == 200, (route, r.text[:200])
    _strict(r.text)


def test_unknown_ticker_and_injection_are_safe(client):
    r = client.get("/api/stock/..%2F..%2Fetc/terminal")
    assert r.status_code in (400, 404, 422)
    r = client.get("/api/stock/ZZZZ9/terminal")
    assert r.status_code in (200, 400, 404)
    if r.status_code == 200:
        _strict(r.text)


def test_research_and_strategy_never_emit_production_buy(client):
    research = _strict(client.get("/api/strategy/research").text)
    assert research.get("production_buy_emitted", False) is False
    for s in _strict(client.get("/api/strategy").text)["strategies"]:
        assert s["profitable_claim"] is False
        assert s["research_validation"].get("production_status") is None


def test_ops_status_exposes_security_and_jobs(client):
    ops = _strict(client.get("/api/ops/status").text)
    assert "security" in ops and "jobs" in ops
    assert ops["security"]["idp"].startswith("NOT_CONFIGURED")
