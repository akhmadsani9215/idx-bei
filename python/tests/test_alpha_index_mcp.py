"""Unit tests for Alpha Index client + MCP tool wiring (mocked HTTP)."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

from idx.alpha_index import (
    AlphaIndexError,
    broker_summary,
    foreign_flow,
)
from idx.mcp.server import TOOLS, handle_tool_call


def test_alpha_tools_registered_in_mcp():
    names = {t["name"] for t in TOOLS}
    assert "alpha_broker_summary" in names
    assert "alpha_stock_history" in names
    assert "alpha_foreign_flow" in names


def test_validation_rejects_bad_inputs(monkeypatch):
    monkeypatch.setenv("ALPHA_INDEX_API_KEY", "test-key-not-real")
    with pytest.raises(AlphaIndexError, match="YYYY-MM-DD"):
        broker_summary(ticker="BBCA", date_from="22-09-2026", date_to="2026-09-22")
    with pytest.raises(AlphaIndexError, match="investor"):
        broker_summary(
            ticker="BBCA",
            date_from="2026-09-22",
            date_to="2026-09-22",
            investor="foreign",
        )


def test_missing_api_key(monkeypatch):
    monkeypatch.setenv("ALPHA_INDEX_SKIP_DOTENV", "1")
    monkeypatch.delenv("ALPHA_INDEX_API_KEY", raising=False)
    monkeypatch.delenv("INDEXALPHA_API_KEY", raising=False)
    with pytest.raises(AlphaIndexError, match="ALPHA_INDEX_API_KEY"):
        broker_summary(ticker="BBCA", date_from="2026-09-22", date_to="2026-09-22")


def test_broker_summary_success_mocked(monkeypatch):
    monkeypatch.setenv("ALPHA_INDEX_API_KEY", "test-key-not-real")
    payload = {
        "success": True,
        "data": [
            {
                "code": "YP",
                "buy_freq": 1,
                "buy_volume": 100,
                "buy_value": 1000.0,
                "sell_freq": 0,
                "sell_volume": 0,
                "sell_value": 0.0,
                "buy_avg": 10.0,
                "sell_avg": 0.0,
            }
        ],
        "error": None,
    }
    raw = json.dumps(payload).encode()

    class _Resp:
        status = 200

        def read(self):
            return raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=_Resp()):
        out = broker_summary(
            ticker="bbca",
            date_from="2026-09-22",
            date_to="2026-09-22",
            investor="all",
            market="RG",
        )
    assert out["success"] is True
    assert out["count"] == 1
    assert out["endpoint"] == "/stocks/broker-summary"
    assert out["params"]["ticker"] == "BBCA"
    # Secret must not appear in serialized result
    blob = json.dumps(out)
    assert "test-key-not-real" not in blob
    assert "Authorization" not in blob


def test_http_error_redacts_and_mcp_tool(monkeypatch):
    monkeypatch.setenv("ALPHA_INDEX_API_KEY", "super-secret-token-xyz")

    def _boom(*_a, **_k):
        raise urllib.error.HTTPError(
            url="https://api.indexalpha.id/stocks/broker-summary",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"Bearer super-secret-token-xyz rejected"}'),
        )

    with patch("urllib.request.urlopen", side_effect=_boom):
        text = handle_tool_call(
            "alpha_broker_summary",
            {
                "ticker": "BBCA",
                "from": "2026-09-22",
                "to": "2026-09-22",
                "investor": "all",
                "market": "RG",
            },
        )
    assert "super-secret-token-xyz" not in text
    parsed = json.loads(text)
    assert parsed["success"] is False


def test_mcp_alpha_stock_history_mocked(monkeypatch):
    monkeypatch.setenv("ALPHA_INDEX_API_KEY", "test-key-not-real")
    payload = {"success": True, "data": [{"date": "2026-09-22", "close": 100}], "error": None}
    raw = json.dumps(payload).encode()

    class _Resp:
        status = 200

        def read(self):
            return raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=_Resp()):
        text = handle_tool_call(
            "alpha_stock_history",
            {"ticker": "BBCA", "from": "2026-09-22", "to": "2026-09-22"},
        )
    parsed = json.loads(text)
    assert parsed["success"] is True
    assert parsed["endpoint"] == "/stocks/ohlcv"


def test_foreign_flow_mocked(monkeypatch):
    monkeypatch.setenv("ALPHA_INDEX_API_KEY", "test-key-not-real")
    payload = {
        "success": True,
        "data": {"buy_value": 1, "sell_value": 2, "net_value": -1},
        "error": None,
    }
    raw = json.dumps(payload).encode()

    class _Resp:
        status = 200

        def read(self):
            return raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=_Resp()):
        out = foreign_flow(
            ticker="BBCA", date_from="2026-09-22", date_to="2026-09-22", market="RG"
        )
    assert out["success"] is True
    assert out["endpoint"] == "/foreign-flow"
