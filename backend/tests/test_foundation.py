import os
import tempfile
import unittest

import pandas as pd

from backtesting import BacktestConfig, HistoricalBacktestEngine
from config import Settings
from engine.broker_engine import MT5ExecutionEngine
from engine.institutional_confluence import InstitutionalConfluenceEngine
from ledger import AuraLedger
from risk_guard import RiskGuard


class AuraFoundationTests(unittest.TestCase):
    def settings(self, mode: str = "paper", database_path: str = ":memory:") -> Settings:
        return Settings(
            execution_mode=mode,
            mt5_account=None,
            mt5_password=None,
            mt5_server=None,
            cors_origins=["http://localhost:3000"],
            default_symbol="EURUSD",
            max_risk_percent=1.0,
            mt5_deviation=20,
            database_path=database_path,
            paper_starting_balance=10_000.0,
            max_open_positions=3,
            max_trades_per_day=8,
            max_daily_loss_percent=2.0,
            execution_api_key=None,
            news_provider="tradingeconomics",
            trading_economics_api_key=None,
            news_countries=["united states", "euro area", "united kingdom", "japan"],
            news_min_importance=3,
            news_block_before_minutes=30,
            news_block_after_minutes=15,
            news_cache_seconds=60,
        )

    def test_engine_never_invents_setup_when_data_is_missing(self):
        engine = InstitutionalConfluenceEngine()
        result = engine.find_high_probability_setup(pd.DataFrame(), "EURUSD")
        self.assertEqual(result["status"], "WAITING_FOR_DATA")
        self.assertNotIn("action", result)
        self.assertEqual(result["confluence_score"], 0)

    def test_paper_order_is_explicitly_labeled(self):
        broker = MT5ExecutionEngine(self.settings("paper"))
        result = broker.send_order("EURUSD", "BUY", 1.085, 1.0825, 1.0925, 0.5)
        self.assertEqual(result["status"], "PAPER_FILLED")
        self.assertEqual(result["mode"], "paper")
        self.assertTrue(str(result["order_id"]).startswith("PAPER-"))

    def test_invalid_buy_structure_is_rejected(self):
        broker = MT5ExecutionEngine(self.settings("paper"))
        with self.assertRaises(ValueError):
            broker.send_order("EURUSD", "BUY", 1.085, 1.09, 1.08, 0.5)

    def test_position_size_preview_uses_same_paper_model_as_execution(self):
        broker = MT5ExecutionEngine(self.settings("paper"))
        preview = broker.preview_position_size("EURUSD", "BUY", 1.085, 1.0825, 0.5, 10_000)
        result = broker.send_order("EURUSD", "BUY", 1.085, 1.0825, 1.0925, 0.5, paper_balance=10_000)
        self.assertEqual(preview["basis"], "PAPER_MODEL")
        self.assertEqual(preview["lots"], result["lots"])
        self.assertEqual(preview["risk_amount"], 50.0)

    def test_simulation_market_status_never_invents_live_spread(self):
        broker = MT5ExecutionEngine(self.settings("paper"))
        df, source = broker.get_market_candles("EURUSD", n_bars=48)
        status = broker.market_status("EURUSD", df=df, source=source)
        self.assertEqual(status["source"], "SIMULATION")
        self.assertIsNone(status["spread"])
        self.assertIsNone(status["spread_points"])
        self.assertIsNotNone(status["volatility_percent"])

    def test_ledger_persists_order_and_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AuraLedger(os.path.join(tmp, "aura.db"), 10_000)
            broker = MT5ExecutionEngine(self.settings("paper"))
            result = broker.send_order("EURUSD", "BUY", 1.085, 1.0825, 1.0925, 0.5)
            refs = ledger.record_execution(result)
            self.assertTrue(refs["ledger_order_id"].startswith("ORD-"))
            self.assertEqual(len(ledger.open_positions()), 1)
            self.assertEqual(ledger.metrics()["trades_today"], 1)

    def test_duplicate_symbol_risk_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AuraLedger(os.path.join(tmp, "aura.db"), 10_000)
            broker = MT5ExecutionEngine(self.settings("paper"))
            result = broker.send_order("EURUSD", "BUY", 1.085, 1.0825, 1.0925, 0.5)
            ledger.record_execution(result)
            guard = RiskGuard(ledger, 3, 8, 2.0, True)
            decision = guard.evaluate("EURUSD")
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.code, "DUPLICATE_SYMBOL")

    def test_closing_paper_position_updates_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AuraLedger(os.path.join(tmp, "aura.db"), 10_000)
            broker = MT5ExecutionEngine(self.settings("paper"))
            result = broker.send_order("EURUSD", "BUY", 1.085, 1.0825, 1.0925, 0.5)
            refs = ledger.record_execution(result)
            closed = ledger.close_position(refs["position_id"], 1.086)
            self.assertEqual(closed["status"], "CLOSED")
            self.assertGreater(ledger.metrics()["balance"], 10_000)

    def test_performance_summary_uses_only_closed_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AuraLedger(os.path.join(tmp, "aura.db"), 10_000)
            broker = MT5ExecutionEngine(self.settings("paper"))
            first = broker.send_order("EURUSD", "BUY", 1.085, 1.0825, 1.0925, 0.5)
            first_refs = ledger.record_execution(first)
            ledger.close_position(first_refs["position_id"], 1.086)

            summary = ledger.performance_summary()
            self.assertEqual(summary["closed_trades"], 1)
            self.assertEqual(summary["wins"], 1)
            self.assertEqual(summary["losses"], 0)
            self.assertGreater(summary["net_realized"], 0)
            self.assertEqual(len(summary["equity_curve"]), 1)



    def test_historical_killzone_uses_candle_time(self):
        engine = InstitutionalConfluenceEngine()
        london = engine.is_killzone_active(pd.Timestamp("2026-01-05T08:00:00Z"))
        off_hours = engine.is_killzone_active(pd.Timestamp("2026-01-05T12:00:00Z"))
        self.assertTrue(london["active"])
        self.assertEqual(london["session"], "London Open")
        self.assertFalse(off_hours["active"])

    def test_backtest_uses_conservative_stop_first_intrabar_assumption(self):
        class AlwaysSetup:
            def find_high_probability_setup(self, df, symbol):
                return {
                    "status": "A_PLUS_SETUP",
                    "action": "BUY",
                    "entry": 1.0,
                    "sl": 0.995,
                    "tp": 1.015,
                    "confluence_score": 100,
                    "session": "Test",
                }

        dates = pd.date_range("2026-01-01T00:00:00Z", periods=100, freq="15min")
        bars = pd.DataFrame({
            "time": dates,
            "open": [1.0] * 100,
            "high": [1.02] * 100,
            "low": [0.99] * 100,
            "close": [1.0] * 100,
        })
        runner = HistoricalBacktestEngine(AlwaysSetup())
        result = runner.run(
            bars,
            BacktestConfig(symbol="EURUSD", risk_percent=1.0, max_hold_bars=4, warmup_bars=60),
            source="TEST_OHLC",
        )
        self.assertGreater(result["metrics"]["total_trades"], 0)
        self.assertTrue(all(trade["exit_reason"] == "SL" for trade in result["trades"]))
        self.assertLess(result["metrics"]["ending_balance"], result["metrics"]["initial_balance"])
        self.assertEqual(result["assumptions"]["intrabar_both_levels"], "STOP_FIRST")

    def test_backtest_run_is_persisted_and_retrievable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AuraLedger(os.path.join(tmp, "aura.db"), 10_000)
            result = {
                "strategy": "AURA Institutional Confluence",
                "strategy_version": "3.5",
                "symbol": "EURUSD",
                "timeframe": "M15",
                "source": "USER_OHLC",
                "bars": 100,
                "from": "2026-01-01T00:00:00+00:00",
                "to": "2026-01-02T00:45:00+00:00",
                "assumptions": {},
                "metrics": {
                    "total_trades": 1,
                    "total_return_percent": 1.0,
                    "max_drawdown_percent": 0.0,
                },
                "equity_curve": [],
                "trades": [],
            }
            run_id = ledger.record_backtest(result)
            saved = ledger.backtest_run(run_id)
            self.assertIsNotNone(saved)
            self.assertEqual(saved["id"], run_id)
            self.assertEqual(saved["source"], "USER_OHLC")
            self.assertEqual(ledger.recent_backtests(5)[0]["id"], run_id)


if __name__ == "__main__":
    unittest.main()
