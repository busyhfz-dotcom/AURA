import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from alerts.alert_engine import AlertEngine
from alerts.telegram_notifier import TelegramNotifier
from news_calendar import EconomicCalendarService
from storage.db import VertexStore


class NewsCalendarTests(unittest.TestCase):
    def test_unconfigured_guard_never_claims_safe(self):
        service = EconomicCalendarService(provider=None, api_key=None)
        status = service.status("EURUSD")
        self.assertFalse(status["configured"])
        self.assertFalse(status["safe"])
        self.assertFalse(status["active"])

    def test_high_impact_matching_currency_activates_embargo(self):
        service = EconomicCalendarService(provider="finnhub", api_key="test-key")
        now = datetime.now(timezone.utc)
        service._events = [{
            "event": "US CPI", "country": "UNITED STATES", "currency": "USD",
            "time": (now + timedelta(minutes=10)).isoformat(), "impact": "HIGH",
            "actual": None, "estimate": None, "previous": None,
        }]
        service._cached_at = time.time()
        status = service.status("EURUSD")
        self.assertTrue(status["active"])
        self.assertFalse(status["safe"])

    def test_provider_error_never_claims_safe(self):
        service = EconomicCalendarService(provider="finnhub", api_key="test-key")
        service._last_error = "provider down"
        service._cached_at = time.time()
        status = service.status("EURUSD")
        self.assertFalse(status["safe"])
        self.assertEqual(status["provider_error"], "provider down")


class AlertEngineTests(unittest.TestCase):
    @contextmanager
    def _store(self, tmp):
        store = VertexStore(os.path.join(tmp, "vertex.db"))
        try:
            yield store
        finally:
            store._conn.close()

    def test_high_risk_fires_alert_and_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp, self._store(tmp) as store:
            engine = AlertEngine(store, TelegramNotifier(None, None), cooldown_seconds=900)
            risk = {"risk_score": 85, "risk_label": "HIGH", "reasons": ["Elevated volatility."], "news_embargo_active": False}
            signal = {"status": "SCANNING", "confluence_score": 20}
            fired = engine.evaluate("BTCUSDT", "CRYPTO", risk, signal)
            self.assertEqual(len(fired), 1)
            self.assertEqual(fired[0]["category"], "RISK")
            self.assertEqual(len(store.recent_alerts()), 1)

    def test_cooldown_prevents_duplicate_alert_spam(self):
        with tempfile.TemporaryDirectory() as tmp, self._store(tmp) as store:
            engine = AlertEngine(store, TelegramNotifier(None, None), cooldown_seconds=900)
            risk = {"risk_score": 90, "risk_label": "HIGH", "reasons": [], "news_embargo_active": False}
            signal = {"status": "SCANNING", "confluence_score": 0}
            first = engine.evaluate("ETHUSDT", "CRYPTO", risk, signal)
            second = engine.evaluate("ETHUSDT", "CRYPTO", risk, signal)
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 0)

    def test_new_setup_is_logged_as_signal_event_and_alert(self):
        with tempfile.TemporaryDirectory() as tmp, self._store(tmp) as store:
            engine = AlertEngine(store, TelegramNotifier(None, None))
            risk = {"risk_score": 10, "risk_label": "LOW", "reasons": [], "news_embargo_active": False}
            signal = {
                "symbol": "EURUSD", "status": "A_PLUS_SETUP", "action": "BUY",
                "entry": 1.085, "sl": 1.08, "tp": 1.10, "confluence_score": 95, "session": "London Open",
            }
            fired = engine.evaluate("EURUSD", "FOREX", risk, signal)
            self.assertEqual(len(fired), 1)
            self.assertEqual(fired[0]["category"], "SETUP")
            self.assertEqual(len(store.recent_signal_events()), 1)

            # Same setup again should not duplicate the alert.
            fired_again = engine.evaluate("EURUSD", "FOREX", risk, signal)
            self.assertEqual(len(fired_again), 0)


if __name__ == "__main__":
    unittest.main()
