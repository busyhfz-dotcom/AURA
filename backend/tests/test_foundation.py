import os
import tempfile
import unittest

import pandas as pd

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


if __name__ == "__main__":
    unittest.main()
