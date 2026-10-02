import unittest

import pandas as pd

from engine.confluence_engine import ConfluenceEngine
from engine.risk_engine import RiskEngine


def _flat_candles(n=100, base=100.0):
    dates = pd.date_range("2026-01-01T00:00:00Z", periods=n, freq="15min")
    return pd.DataFrame({
        "time": dates,
        "open": [base] * n,
        "high": [base + 0.5] * n,
        "low": [base - 0.5] * n,
        "close": [base] * n,
    })


class ConfluenceEngineTests(unittest.TestCase):
    def test_never_invents_setup_when_data_is_missing(self):
        engine = ConfluenceEngine()
        result = engine.find_setup(pd.DataFrame(), "BTCUSDT")
        self.assertEqual(result["status"], "WAITING_FOR_DATA")
        self.assertNotIn("action", result)
        self.assertEqual(result["confluence_score"], 0)

    def test_flat_market_never_produces_a_plus_setup(self):
        engine = ConfluenceEngine()
        result = engine.find_setup(_flat_candles(), "EURUSD")
        self.assertIn(result["status"], {"SCANNING", "WAITING_FOR_DATA"})
        self.assertNotEqual(result["status"], "A_PLUS_SETUP")

    def test_killzone_uses_evaluation_time_not_wallclock(self):
        engine = ConfluenceEngine()
        london = engine.is_killzone_active(pd.Timestamp("2026-01-05T08:00:00Z"))
        off_hours = engine.is_killzone_active(pd.Timestamp("2026-01-05T20:00:00Z"))
        self.assertTrue(london["active"])
        self.assertFalse(off_hours["active"])


class RiskEngineTests(unittest.TestCase):
    def test_no_data_yields_unavailable_not_fabricated_low_risk(self):
        engine = RiskEngine()
        result = engine.score("BTCUSDT", "CRYPTO", pd.DataFrame(), killzone_active=False, news_active=False)
        self.assertEqual(result["volatility_state"], "UNAVAILABLE")

    def test_news_embargo_always_adds_risk(self):
        engine = RiskEngine()
        candles = _flat_candles()
        without_news = engine.score("EURUSD", "FOREX", candles, killzone_active=False, news_active=False)
        with_news = engine.score("EURUSD", "FOREX", candles, killzone_active=False, news_active=True)
        self.assertGreater(with_news["risk_score"], without_news["risk_score"])
        self.assertTrue(with_news["news_embargo_active"])

    def test_risk_score_bounded_0_to_100(self):
        engine = RiskEngine()
        result = engine.score("BTCUSDT", "CRYPTO", _flat_candles(), killzone_active=True, news_active=True, change_percent_24h=40.0)
        self.assertGreaterEqual(result["risk_score"], 0)
        self.assertLessEqual(result["risk_score"], 100)


if __name__ == "__main__":
    unittest.main()
