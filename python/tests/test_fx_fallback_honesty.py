"""FX fallback honesty — live / cached / stale / default / unavailable / Yahoo flags."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pandas as pd
import pytest

from idx.core.currency import (
    DEFAULT_USD_IDR_RATE,
    fetch_live_usd_idr_rate,
    fx_status,
    resolve_usd_idr_quote,
    yahoo_fx_allowed,
)


@pytest.fixture
def fx_env(monkeypatch, tmp_path):
    cache = tmp_path / "usd_idr_rate.json"
    monkeypatch.setattr("idx.core.currency.CACHE_FILE", str(cache))
    monkeypatch.delenv("RITELINSIGHT_ALLOW_YAHOO_FX", raising=False)
    monkeypatch.delenv("RITELINSIGHT_ALLOW_OPEN_ER_API", raising=False)
    return cache


def _write_cache(path, rate: float, *, age_seconds: float, origin: str = "yfinance_yahoo"):
    payload = {
        "rate": rate,
        "timestamp": time.time() - age_seconds,
        "source": origin,
        "origin": origin,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_yahoo_disabled_by_default(fx_env):
    assert yahoo_fx_allowed() is False
    with patch("yfinance.Ticker") as mock_t:
        assert fetch_live_usd_idr_rate() is None
        mock_t.assert_not_called()


def test_default_constant_not_market_quote(fx_env):
    q = resolve_usd_idr_quote(force_refresh=True, default_rate=16111.0)
    assert q["status"] == "default_constant"
    assert q["rate"] == 16111.0
    assert q["is_live"] is False
    assert q["is_market_quote"] is False
    assert q["is_default_constant"] is True
    assert q["is_verified_fx"] is False
    assert q["quality"] == "CONSTANT"
    assert q["confidence"] <= 0.2
    notes = (q.get("notes") or "").lower()
    assert "not a live" in notes or "default constant" in notes
    assert "market quote" in notes


def test_unavailable_when_default_disallowed(fx_env):
    q = resolve_usd_idr_quote(force_refresh=True, allow_default=False)
    assert q["status"] == "unavailable"
    assert q["rate"] is None
    assert q["is_market_quote"] is False
    assert q["is_live"] is False
    assert q["is_verified_fx"] is False


def test_cached_quote_not_live(fx_env):
    _write_cache(fx_env, 17000.0, age_seconds=60, origin="open_er_api")
    q = resolve_usd_idr_quote(force_refresh=False)
    assert q["status"] == "cached"
    assert q["rate"] == 17000.0
    assert q["is_live"] is False
    assert q["is_market_quote"] is True
    assert q["is_default_constant"] is False
    assert q["origin"] == "open_er_api"
    assert q["source"].startswith("cached:")
    assert "not a live" in (q.get("notes") or "").lower()


def test_stale_cache_quote(fx_env):
    _write_cache(fx_env, 16800.0, age_seconds=999999, origin="yfinance_yahoo")
    q = resolve_usd_idr_quote(force_refresh=False)
    assert q["status"] == "stale_cache"
    assert q["rate"] == 16800.0
    assert q["is_live"] is False
    assert q["is_market_quote"] is True
    assert q["is_default_constant"] is False
    assert "stale" in (q.get("notes") or "").lower()


def test_live_quote_when_yahoo_opt_in(fx_env, monkeypatch):
    monkeypatch.setenv("RITELINSIGHT_ALLOW_YAHOO_FX", "1")
    monkeypatch.delenv("RITELINSIGHT_ALLOW_OPEN_ER_API", raising=False)

    class _T:
        fast_info = type("FI", (), {"last_price": 16555.0})()

        def history(self, period="5d"):
            return pd.DataFrame()

    with patch("yfinance.Ticker", return_value=_T()):
        q = resolve_usd_idr_quote(force_refresh=True)
    assert q["status"] == "live"
    assert q["rate"] == 16555.0
    assert q["is_live"] is True
    assert q["is_market_quote"] is True
    assert q["is_default_constant"] is False
    assert q["is_verified_fx"] is False
    assert q["origin"] == "yfinance_yahoo"
    assert "LICENSE_REVIEW_REQUIRED" in (q.get("license_status") or "")


def test_fx_status_exposes_current_quote_honesty(fx_env):
    st = fx_status()
    assert st["hidden_yahoo_production_dependency"] is False
    cq = st["current_quote"]
    assert cq["status"] in {
        "live",
        "cached",
        "stale_cache",
        "default_constant",
        "unavailable",
    }
    assert "is_market_quote" in cq
    assert "is_default_constant" in cq
    assert cq["is_verified_fx"] is False
    if cq["status"] == "default_constant":
        assert cq["is_market_quote"] is False
        assert cq["is_live"] is False


def test_dividend_success_includes_fx(monkeypatch, fx_env):
    """When analysis succeeds, usd_idr lineage must be present and honest."""
    from idx import dividend as div_mod

    details = {
        "BBCA": {
            "Dividen": [
                {
                    "Nama": "Bank Central Asia",
                    "CashDividenPerSaham": 100,
                    "CashDividenPerSahamMU": "IDR",
                    "CashDividenTotal": 0,
                    "CashDividenTotalMU": "IDR",
                    "TanggalCum": "2026-01-10",
                    "TanggalExRegulerDanNegosiasi": "2026-01-13",
                    "TanggalDPS": "2026-01-10",
                    "TanggalPembayaran": "2026-01-20",
                    "TahunBuku": "2025",
                }
            ],
            "Profiles": [{"NamaEmiten": "BBCA", "JumlahSaham": 1e11}],
        }
    }
    dates = pd.bdate_range("2025-12-01", periods=40)
    closes = pd.Series(range(9000, 9040), dtype=float)
    stock = pd.DataFrame(
        {
            "Date": dates,
            "StockCode": "BBCA",
            "Close": closes,
            "NetForeignFlow": 0.0,
            "ListedShares": 1e11,
        }
    )
    ratios = pd.DataFrame(
        columns=["code", "eps", "roe", "deRatio", "per", "priceBV", "opini", "profitAttrOwner"]
    )
    monkeypatch.setattr(
        "idx.dividend.resolve_usd_idr_quote",
        lambda **_k: {
            "rate": DEFAULT_USD_IDR_RATE,
            "status": "default_constant",
            "source": "default_constant",
            "origin": "default_constant",
            "quality": "CONSTANT",
            "confidence": 0.1,
            "is_live": False,
            "is_market_quote": False,
            "is_default_constant": True,
            "is_verified_fx": False,
            "notes": "DEFAULT CONSTANT — not a live FX quote",
        },
    )
    out = div_mod.analyze_stock_dividend(
        "BBCA", details_dict=details, stock_df=stock, ratios_df=ratios
    )
    assert out["has_dividend"] is True
    fx = out["usd_idr"]
    assert fx["status"] == "default_constant"
    assert fx["is_market_quote"] is False
    assert fx["is_live"] is False
    assert fx["is_verified_fx"] is False
