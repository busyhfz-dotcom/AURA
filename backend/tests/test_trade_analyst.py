import unittest

import numpy as np
import pandas as pd

from engine.confluence_engine import ConfluenceEngine
from engine.trade_analyst import TradeAnalyst
from engine.indicators import rsi


def _trending_candles(n=260, base=100.0, drift=0.05, noise=0.15, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-01T00:00:00Z", periods=n, freq="15min")
    returns = rng.normal(drift, noise, n)
    close = base + np.cumsum(returns)
    high = close + np.abs(rng.normal(0.2, 0.1, n))
    low = close - np.abs(rng.normal(0.2, 0.1, n))
    open_price = np.concatenate(([base], close[:-1]))
    volume = np.abs(rng.normal(1000, 100, n)) + np.linspace(0, 400, n)
    return pd.DataFrame({"time": dates, "open": open_price, "high": high, "low": low, "close": close, "volume": volume})


def _flat_candles(n=260, base=100.0):
    dates = pd.date_range("2026-01-01T00:00:00Z", periods=n, freq="15min")
    return pd.DataFrame({
        "time": dates, "open": [base] * n, "high": [base + 0.05] * n,
        "low": [base - 0.05] * n, "close": [base] * n, "volume": [100] * n,
    })


NEWS_INACTIVE = {"active": False, "configured": False}
NEWS_ACTIVE = {"active": True, "configured": True}


class TradeAnalystTests(unittest.TestCase):
    def setUp(self):
        self.analyst = TradeAnalyst(ConfluenceEngine())

    def test_uptrend_across_timeframes_leans_bullish(self):
        frames = {tf: _trending_candles(seed=1) for tf in ("15m", "1h", "4h")}
        risk = {"risk_label": "MODERATE", "risk_score": 30}
        result = self.analyst.analyze("BTCUSDT", frames, risk, NEWS_INACTIVE)
        self.assertGreaterEqual(result["composite_bullish_percent"], 50)
        self.assertIn(result["recommendation"], {"BUY", "WAIT"})
        self.assertIsNotNone(result["disclaimer"])

    def test_downtrend_across_timeframes_leans_bearish(self):
        frames = {tf: _trending_candles(drift=-0.05, seed=2) for tf in ("15m", "1h", "4h")}
        risk = {"risk_label": "MODERATE", "risk_score": 30}
        result = self.analyst.analyze("ETHUSDT", frames, risk, NEWS_INACTIVE)
        self.assertLessEqual(result["composite_bullish_percent"], 50)

    def test_flat_market_recommends_wait(self):
        frames = {tf: _flat_candles() for tf in ("15m", "1h", "4h")}
        risk = {"risk_label": "LOW", "risk_score": 5}
        result = self.analyst.analyze("EURUSD", frames, risk, NEWS_INACTIVE)
        self.assertEqual(result["recommendation"], "WAIT")

    def test_news_embargo_forces_wait_even_with_strong_trend(self):
        frames = {tf: _trending_candles(seed=1) for tf in ("15m", "1h", "4h")}
        risk = {"risk_label": "MODERATE", "risk_score": 30}
        result = self.analyst.analyze("BTCUSDT", frames, risk, NEWS_ACTIVE)
        self.assertEqual(result["recommendation"], "WAIT")
        self.assertIsNotNone(result["override_reason"])
        self.assertEqual(result["suggested_risk_percent"], 0.0)

    def test_high_composite_risk_forces_wait(self):
        frames = {tf: _trending_candles(seed=1) for tf in ("15m", "1h", "4h")}
        risk = {"risk_label": "HIGH", "risk_score": 85}
        result = self.analyst.analyze("BTCUSDT", frames, risk, NEWS_INACTIVE)
        self.assertEqual(result["recommendation"], "WAIT")
        self.assertIsNotNone(result["override_reason"])

    def test_probability_percent_bounded_and_method_breakdown_present(self):
        frames = {tf: _trending_candles(seed=3) for tf in ("15m", "1h", "4h")}
        risk = {"risk_label": "LOW", "risk_score": 10}
        result = self.analyst.analyze("XAUUSD", frames, risk, NEWS_INACTIVE)
        self.assertGreaterEqual(result["probability_percent"], 0)
        self.assertLessEqual(result["probability_percent"], 100)
        self.assertEqual(len(result["method_breakdown"]), 4)
        weights = sum(m["weight_percent"] for m in result["method_breakdown"])
        self.assertEqual(weights, 100)

    def test_missing_data_never_fabricates_a_confident_call(self):
        frames = {"15m": pd.DataFrame(), "1h": pd.DataFrame(), "4h": pd.DataFrame()}
        risk = {"risk_label": "LOW", "risk_score": 0}
        result = self.analyst.analyze("NEWSYMBOL", frames, risk, NEWS_INACTIVE)
        self.assertEqual(result["recommendation"], "WAIT")
        self.assertIsNone(result["entry_plan"])

    def test_news_provider_failure_blocks_calls_and_entry_plan(self):
        frames = {tf: _trending_candles(seed=1) for tf in ("15m", "1h", "4h")}
        risk = {"risk_label": "LOW", "risk_score": 10}
        result = self.analyst.analyze("BTCUSDT", frames, risk, {"configured": True, "safe": False, "provider_error": "HTTP 403"})
        self.assertEqual(result["recommendation"], "WAIT")
        self.assertIsNone(result["entry_plan"])
        self.assertIsNone(result["calibrated_probability_percent"])
        self.assertEqual(result["score_type"], "UNCALIBRATED_CONFLUENCE")

    def test_unconfigured_news_guard_is_unknown_and_blocks_calls(self):
        frames = {tf: _trending_candles(seed=1) for tf in ("15m", "1h", "4h")}
        result = self.analyst.analyze("BTCUSDT", frames, {"risk_label": "LOW", "risk_score": 10}, NEWS_INACTIVE)
        self.assertEqual(result["override_code"], "NEWS_UNKNOWN")
        self.assertEqual(result["recommendation"], "WAIT")

    def test_directional_trend_without_structural_trigger_is_not_a_trade_call(self):
        frames = {tf: _trending_candles(seed=1) for tf in ("15m", "1h", "4h")}
        result = self.analyst.analyze("BTCUSDT", frames, {"risk_label": "LOW", "risk_score": 10}, NEWS_INACTIVE)
        if result["recommendation"] in {"BUY", "SELL"}:
            self.assertEqual(result["entry_plan"]["basis"], "STRUCTURAL_TRIGGER")
        else:
            self.assertIsNone(result["entry_plan"])

    def test_confirmed_trigger_and_clear_news_can_produce_a_call(self):
        class ConfirmedConfluence:
            def find_setup(self, _df, symbol):
                return {"symbol": symbol, "status": "A_PLUS_SETUP", "action": "BUY", "confluence_score": 90,
                        "entry": 110.0, "sl": 108.0, "tp": 116.0, "rr": "1:3.0"}

        frames = {tf: _trending_candles(seed=1) for tf in ("15m", "1h", "4h")}
        result = TradeAnalyst(ConfirmedConfluence()).analyze(
            "BTCUSDT", frames, {"risk_label": "LOW", "risk_score": 10},
            {"configured": True, "safe": True, "active": False},
        )
        self.assertEqual(result["recommendation"], "BUY")
        self.assertEqual(result["entry_plan"]["basis"], "STRUCTURAL_TRIGGER")
        self.assertEqual(result["suggested_risk_percent"], 0.5)

    def test_rsi_handles_zero_loss_and_zero_gain(self):
        self.assertEqual(float(rsi(pd.Series(range(50))).iloc[-1]), 100.0)
        self.assertEqual(float(rsi(pd.Series(range(50, 0, -1))).iloc[-1]), 0.0)
        self.assertEqual(float(rsi(pd.Series([10.0] * 50)).iloc[-1]), 50.0)


if __name__ == "__main__":
    unittest.main()
