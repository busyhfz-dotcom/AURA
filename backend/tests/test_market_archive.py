import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from storage.db import VertexStore


class MarketArchiveTests(unittest.TestCase):
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
