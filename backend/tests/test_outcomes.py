import unittest
from datetime import datetime, timedelta, timezone

from engine.outcomes import audit_call


class OutcomeAuditTests(unittest.TestCase):
    def setUp(self):
        self.called = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        self.call = {
            "id": "CALL-1", "symbol": "BTCUSDT", "asset_class": "CRYPTO",
            "recommendation": "BUY", "entry": 100.0, "sl": 98.0, "tp": 106.0,
            "methodology_version": 2,
            "created_at": self.called.isoformat(),
        }

    def bar(self, index, low, high):
        return {"open_time": (self.called + timedelta(minutes=15 * index)).isoformat(),
                "open": 100.0, "high": high, "low": low, "close": 100.0}

    def test_target_after_unambiguous_fill(self):
        bars = [self.bar(0, 99.5, 101.0), self.bar(1, 100.0, 106.5)]
        result = audit_call(self.call, bars)
        self.assertEqual(result["status"], "WIN")
        self.assertEqual(result["gross_r"], 3.0)

    def test_same_bar_fill_and_exit_is_ambiguous(self):
        self.assertEqual(audit_call(self.call, [self.bar(0, 99.5, 106.5)])["status"], "AMBIGUOUS")

    def test_missing_bar_is_not_counted_as_a_win(self):
        bars = [self.bar(0, 99.5, 101.0), self.bar(2, 100.0, 106.5)]
        self.assertEqual(audit_call(self.call, bars)["status"], "DATA_GAP")

    def test_loss_after_fill(self):
        bars = [self.bar(0, 99.5, 101.0), self.bar(1, 97.5, 101.0)]
        self.assertEqual(audit_call(self.call, bars)["status"], "LOSS")

    def test_prior_method_is_excluded_from_current_outcomes(self):
        self.call["methodology_version"] = 1
        self.assertEqual(audit_call(self.call, [self.bar(0, 99.5, 101.0)])['status'], 'LEGACY_METHOD')


if __name__ == "__main__":
    unittest.main()
