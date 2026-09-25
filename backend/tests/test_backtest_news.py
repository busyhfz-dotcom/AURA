import time
import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from backtest import AuraBacktestEngine, BacktestConfig
from news_calendar import EconomicCalendarService


class StubConfluence:
    def find_high_probability_setup(self, df, symbol, as_of=None):
        if len(df) < 42:
            return {
                "symbol": symbol,
                "status": "SCANNING",
                "confluence_score": 50,
                "checklist": {"sweep": True, "displacement": True, "fvg_midpoint": False, "killzone_active": True},
            }
        close = float(df.iloc[-1]["close"])
        return {
            "symbol": symbol,
            "status": "A_PLUS_SETUP",
            "action": "BUY",
            "entry": close,
            "sl": close - 1.0,
            "tp": close + 3.0,
            "rr": "1:3.0",
            "confluence_score": 100,
            "checklist": {"sweep": True, "displacement": True, "fvg_midpoint": True, "killzone_active": True},
        }


class BacktestAndNewsGuardTests(unittest.TestCase):
    def candles(self):
        start = pd.Timestamp("2026-01-01T00:00:00Z")
        rows = []
        price = 100.0
        for i in range(90):
            # After the signal warmup, each candle can fill entry and later reach TP.
            drift = 0.12 if i % 6 else -0.04
            open_price = price
            close = price + drift
            rows.append(
                {
                    "time": start + pd.Timedelta(minutes=15 * i),
                    "open": open_price,
                    "high": max(open_price, close) + 3.4,
                    "low": min(open_price, close) - 0.3,
                    "close": close,
                }
            )
            price = close
        return pd.DataFrame(rows)

    def test_backtest_returns_computed_metrics(self):
        runner = AuraBacktestEngine(StubConfluence())
        result = runner.run(
            self.candles(),
            BacktestConfig(
                symbol="TEST",
                timeframe="M15",
                starting_balance=10_000,
                risk_percent=1.0,
                warmup_bars=40,
                entry_wait_bars=2,
                max_hold_bars=3,
            ),
            source="SIMULATION",
        )
        self.assertEqual(result["validation_level"], "SIMULATION_ONLY")
        self.assertGreater(result["metrics"]["total_trades"], 0)
        self.assertEqual(result["assumptions"]["same_bar_sl_tp_policy"], "SL_FIRST_CONSERVATIVE")
        self.assertEqual(result["assumptions"]["commission_model"], None)
        self.assertTrue(result["equity_curve"])

    def test_unconfigured_news_guard_never_claims_safe(self):
        service = EconomicCalendarService(provider=None, api_key=None)
        status = service.status("EURUSD")
        self.assertFalse(status["configured"])
        self.assertFalse(status["safe"])
        self.assertFalse(status["active"])

    def test_high_impact_event_activates_embargo(self):
        service = EconomicCalendarService(
            provider="finnhub",
            api_key="test-key",
            embargo_before_minutes=30,
            embargo_after_minutes=15,
            cache_seconds=300,
        )
        now = datetime.now(timezone.utc)
        service._events = [
            {
                "event": "US CPI",
                "country": "UNITED STATES",
                "currency": "USD",
                "time": (now + timedelta(minutes=10)).isoformat(),
                "impact": "HIGH",
                "actual": None,
                "estimate": None,
                "previous": None,
                "unit": "%",
            }
        ]
        service._cached_at = time.time()
        status = service.status("EURUSD")
        self.assertTrue(status["configured"])
        self.assertTrue(status["active"])
        self.assertFalse(status["safe"])
        self.assertEqual(len(status["blocking_events"]), 1)


if __name__ == "__main__":
    unittest.main()
