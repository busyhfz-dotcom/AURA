import unittest
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd

from storage.db import VertexStore


class MarketArchiveTests(unittest.TestCase):
    def test_existing_trade_calls_are_marked_as_prior_method(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vertex.db"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE trade_calls (id TEXT PRIMARY KEY, symbol TEXT, asset_class TEXT, recommendation TEXT, probability_percent REAL, suggested_risk_percent REAL, entry REAL, sl REAL, tp REAL, basis TEXT, created_at TEXT)")
                connection.execute("INSERT INTO trade_calls VALUES ('old', 'BTCUSDT', 'CRYPTO', 'BUY', 80, 1, 100, 99, 102, 'ATR_GENERIC', '2026-10-01T00:00:00+00:00')")
            connection.close()
            store = VertexStore(str(path))
            try:
                self.assertEqual(store.recent_trade_calls()[0]["methodology_version"], 1)
                store.add_trade_call({"symbol": "BTCUSDT", "recommendation": "BUY", "probability_percent": 70, "suggested_risk_percent": 0.5, "entry_plan": {"entry": 100, "sl": 99, "tp": 102, "basis": "STRUCTURAL_TRIGGER"}}, "CRYPTO")
                self.assertEqual(store.recent_trade_calls()[0]["methodology_version"], 2)
            finally:
                store._conn.close()

    def test_only_closed_valid_bars_are_archived_and_deduplicated(self):
        store = VertexStore(":memory:")
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        rows = pd.DataFrame([
            {"time": now - timedelta(minutes=30), "open": 100, "high": 102, "low": 99, "close": 101, "volume": 20},
            {"time": now - timedelta(minutes=5), "open": 101, "high": 103, "low": 100, "close": 102, "volume": 21},
            {"time": now - timedelta(minutes=45), "open": 100, "high": 99, "low": 98, "close": 101, "volume": 20},
        ])
        self.assertEqual(store.add_closed_candles("BTCUSDT", "CRYPTO", "BINANCE", "15m", rows), 1)
        self.assertEqual(store.add_closed_candles("BTCUSDT", "CRYPTO", "BINANCE", "15m", rows), 0)
        saved = store.historical_candles("BTCUSDT")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["close"], 101)
        self.assertEqual(saved[0]["source"], "BINANCE")
        readiness = store.research_readiness()
        self.assertEqual(readiness["series"][0]["bars"], 1)
        self.assertFalse(readiness["calibrated_probability_available"])


if __name__ == "__main__":
    unittest.main()
