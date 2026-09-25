import time
import unittest
from datetime import datetime, timedelta, timezone

from news_calendar import EconomicCalendarService


class NewsGuardTests(unittest.TestCase):
    def test_unconfigured_guard_never_claims_safe(self):
        service = EconomicCalendarService(provider=None, api_key=None)
        status = service.status("EURUSD")
        self.assertFalse(status["configured"])
        self.assertFalse(status["safe"])
        self.assertFalse(status["active"])

    def test_high_impact_matching_currency_activates_embargo(self):
        service = EconomicCalendarService(
            provider="finnhub",
            api_key="test-key",
            embargo_before_minutes=30,
            embargo_after_minutes=15,
            cache_seconds=300,
        )
        now = datetime.now(timezone.utc)
        service._events = [{
            "event": "US CPI",
            "country": "UNITED STATES",
            "currency": "USD",
            "time": (now + timedelta(minutes=10)).isoformat(),
            "impact": "HIGH",
            "actual": None,
            "estimate": None,
            "previous": None,
            "unit": "%",
        }]
        service._cached_at = time.time()

        status = service.status("EURUSD")
        self.assertTrue(status["configured"])
        self.assertTrue(status["active"])
        self.assertFalse(status["safe"])
        self.assertEqual(len(status["blocking_events"]), 1)

    def test_irrelevant_currency_does_not_block_symbol(self):
        service = EconomicCalendarService(
            provider="finnhub",
            api_key="test-key",
            embargo_before_minutes=30,
            embargo_after_minutes=15,
            cache_seconds=300,
        )
        now = datetime.now(timezone.utc)
        service._events = [{
            "event": "Japan CPI",
            "country": "JAPAN",
            "currency": "JPY",
            "time": (now + timedelta(minutes=5)).isoformat(),
            "impact": "HIGH",
            "actual": None,
            "estimate": None,
            "previous": None,
            "unit": "%",
        }]
        service._cached_at = time.time()

        status = service.status("EURUSD")
        self.assertTrue(status["configured"])
        self.assertFalse(status["active"])
        self.assertTrue(status["safe"])

    def test_provider_error_never_claims_safe(self):
        service = EconomicCalendarService(provider="finnhub", api_key="test-key")
        service._last_error = "provider down"
        service._cached_at = time.time()
        status = service.status("EURUSD")
        self.assertTrue(status["configured"])
        self.assertFalse(status["safe"])
        self.assertFalse(status["active"])
        self.assertEqual(status["provider_error"], "provider down")


if __name__ == "__main__":
    unittest.main()
