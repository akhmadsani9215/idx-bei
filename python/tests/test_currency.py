"""
Unit tests for the dynamic USD/IDR exchange rate engine.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from idx.core.currency import fx_status, get_usd_idr_rate, resolve_usd_idr_quote


class TestCurrencyEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "usd_idr_rate.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("idx.core.currency.CACHE_FILE")
    def test_default_rate_fallback(self, mock_cache_file):
        mock_cache_file.__str__.return_value = self.cache_file
        with patch("idx.core.currency._fetch_live_quote", return_value=None):
            with patch("idx.core.currency.CACHE_FILE", self.cache_file):
                rate = get_usd_idr_rate(default_rate=16250.0)
                self.assertEqual(rate, 16250.0)
                q = resolve_usd_idr_quote(default_rate=16250.0)
                self.assertEqual(q["source"], "default_constant")

    def test_cached_rate_retrieval(self):
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"rate": 16450.0, "timestamp": 9999999999.0, "source": "test"}, f)

        with patch("idx.core.currency.CACHE_FILE", self.cache_file):
            rate = get_usd_idr_rate()
            self.assertEqual(rate, 16450.0)

    def test_live_rate_fetch_and_cache(self):
        live = {
            "rate": 16325.0,
            "source": "open_er_api",
            "quality": "C",
            "live_attempted": True,
        }
        with patch("idx.core.currency.CACHE_FILE", self.cache_file):
            with patch("idx.core.currency.yahoo_fx_allowed", return_value=False):
                with patch("idx.core.currency.open_er_api_allowed", return_value=True):
                    with patch("idx.core.currency._fetch_live_quote", return_value=live):
                        rate = get_usd_idr_rate(force_refresh=True)
                        self.assertEqual(rate, 16325.0)
                        self.assertTrue(os.path.exists(self.cache_file))
                        with open(self.cache_file) as f:
                            data = json.load(f)
                            self.assertEqual(data["rate"], 16325.0)

    def test_corrupt_cache_handling(self):
        with open(self.cache_file, "w") as f:
            f.write("invalid json{")
        with patch("idx.core.currency.CACHE_FILE", self.cache_file):
            with patch("idx.core.currency.yahoo_fx_allowed", return_value=False):
                with patch("idx.core.currency.open_er_api_allowed", return_value=False):
                    rate = get_usd_idr_rate()
                    self.assertEqual(rate, 16200.0)

    @patch.dict(os.environ, {"RITELINSIGHT_ALLOW_YAHOO_FX": "1"}, clear=False)
    @patch("yfinance.Ticker")
    def test_fetch_live_via_yfinance_fast_info(self, mock_ticker_cls):
        from idx.core.currency import fetch_live_usd_idr_rate

        mock_ticker = mock_ticker_cls.return_value
        mock_ticker.fast_info.last_price = 16250.0
        with patch("idx.core.currency.open_er_api_allowed", return_value=False):
            rate = fetch_live_usd_idr_rate()
        self.assertEqual(rate, 16250.0)

    @patch.dict(os.environ, {"RITELINSIGHT_ALLOW_YAHOO_FX": "1"}, clear=False)
    @patch("yfinance.Ticker")
    def test_fetch_live_via_yfinance_history(self, mock_ticker_cls):
        import pandas as pd

        from idx.core.currency import fetch_live_usd_idr_rate

        mock_ticker = mock_ticker_cls.return_value
        mock_ticker.fast_info = None
        mock_ticker.history.return_value = pd.DataFrame({"Close": [16300.0]})
        with patch("idx.core.currency.open_er_api_allowed", return_value=False):
            rate = fetch_live_usd_idr_rate()
        self.assertEqual(rate, 16300.0)

    @patch.dict(
        os.environ,
        {"RITELINSIGHT_ALLOW_YAHOO_FX": "0", "RITELINSIGHT_ALLOW_OPEN_ER_API": "1"},
        clear=False,
    )
    @patch("yfinance.Ticker")
    @patch("urllib.request.urlopen")
    def test_fetch_live_via_open_exchange_fallback(self, mock_urlopen, mock_ticker_cls):
        from unittest.mock import MagicMock

        from idx.core.currency import fetch_live_usd_idr_rate

        mock_ticker_cls.side_effect = RuntimeError("yfinance down")

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"rates": {"IDR": 16400.0}}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        rate = fetch_live_usd_idr_rate()
        self.assertEqual(rate, 16400.0)

    def test_yahoo_blocked_by_default(self):
        from idx.core.currency import fetch_live_usd_idr_rate

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RITELINSIGHT_ALLOW_YAHOO_FX", None)
            os.environ.pop("RITELINSIGHT_ALLOW_OPEN_ER_API", None)
            with patch("yfinance.Ticker") as mock_ticker:
                rate = fetch_live_usd_idr_rate()
                self.assertIsNone(rate)
                mock_ticker.assert_not_called()

    def test_fx_status_no_hidden_yahoo(self):
        st = fx_status()
        self.assertFalse(st["hidden_yahoo_production_dependency"])
        self.assertIn("license_notes", st)
