from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd
import requests

logger = logging.getLogger("AuraEconomicCalendar")


class EconomicCalendarService:
    """Economic calendar adapter with a strict no-fabrication policy.

    Finnhub is used when configured. If the provider is unavailable, stale, malformed,
    or unconfigured, the service reports that state and never claims the news guard is safe.
    """

    FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"

    def __init__(
        self,
        provider: str | None,
        api_key: str | None,
        embargo_before_minutes: int = 30,
        embargo_after_minutes: int = 15,
        cache_seconds: int = 300,
    ):
        self.provider = (provider or "").strip().lower() or None
        self.api_key = api_key or None
        self.embargo_before_minutes = max(0, int(embargo_before_minutes))
        self.embargo_after_minutes = max(0, int(embargo_after_minutes))
        self.cache_seconds = max(30, int(cache_seconds))
        self._lock = threading.RLock()
        self._cached_at = 0.0
        self._events: list[dict[str, Any]] = []
        self._last_error: str | None = None

    @property
    def configured(self) -> bool:
        return self.provider == "finnhub" and bool(self.api_key)

    @staticmethod
    def _symbol_currencies(symbol: str | None) -> set[str]:
        if not symbol:
            return set()
        symbol = symbol.upper().strip()
        explicit = {
            "XAUUSD": {"USD"},
            "BTCUSD": {"USD"},
            "ETHUSD": {"USD"},
            "NAS100": {"USD"},
            "SP500": {"USD"},
            "USOIL": {"USD"},
        }
        if symbol in explicit:
            return explicit[symbol]
        if len(symbol) == 6 and symbol.isalpha():
            return {symbol[:3], symbol[3:]}
        return set()

    @staticmethod
    def _impact(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"3", "high", "high impact", "high-impact"}:
            return "HIGH"
        if text in {"2", "medium", "moderate", "medium impact", "medium-impact"}:
            return "MEDIUM"
        if text in {"1", "low", "low impact", "low-impact"}:
            return "LOW"
        return "UNKNOWN"

    @staticmethod
    def _event_time(raw: dict[str, Any]) -> Optional[datetime]:
        candidate = raw.get("time") or raw.get("datetime") or raw.get("date")
        if not candidate:
            return None
        try:
            parsed = pd.to_datetime(candidate, utc=True, errors="raise")
            if isinstance(parsed, pd.Timestamp):
                return parsed.to_pydatetime()
        except Exception:
            return None
        return None

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        event_time = self._event_time(raw)
        if event_time is None:
            return None
        country = str(raw.get("country") or "").strip().upper()
        currency = str(raw.get("currency") or raw.get("unit") or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            currency = {
                "UNITED STATES": "USD",
                "US": "USD",
                "USA": "USD",
                "EURO AREA": "EUR",
                "EUROZONE": "EUR",
                "UNITED KINGDOM": "GBP",
                "UK": "GBP",
                "JAPAN": "JPY",
            }.get(country, "")

        return {
            "event": str(raw.get("event") or raw.get("name") or raw.get("indicator") or "Economic event").strip(),
            "country": country or None,
            "currency": currency or None,
            "time": event_time.astimezone(timezone.utc).isoformat(),
            "impact": self._impact(raw.get("impact") or raw.get("importance")),
            "actual": raw.get("actual"),
            "estimate": raw.get("estimate") if "estimate" in raw else raw.get("forecast"),
            "previous": raw.get("prev") if "prev" in raw else raw.get("previous"),
            "unit": raw.get("unit"),
        }

    def _fetch_finnhub(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        params = {
            "from": (now.date() - timedelta(days=1)).isoformat(),
            "to": (now.date() + timedelta(days=2)).isoformat(),
        }
        response = requests.get(
            self.FINNHUB_URL,
            params=params,
            headers={"X-Finnhub-Token": self.api_key or ""},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("economicCalendar", payload if isinstance(payload, list) else [])
        if not isinstance(rows, list):
            raise RuntimeError("Economic calendar provider returned an unexpected payload.")

        events = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            event = self._normalize(row)
            if event:
                events.append(event)
        events.sort(key=lambda item: item["time"])
        return events

    def refresh(self, force: bool = False) -> list[dict[str, Any]]:
        if not self.configured:
            return []

        with self._lock:
            if not force and self._cached_at and time.time() - self._cached_at < self.cache_seconds:
                return list(self._events)
            try:
                if self.provider == "finnhub":
                    events = self._fetch_finnhub()
                else:
                    raise RuntimeError(f"Unsupported economic calendar provider: {self.provider}")
                self._events = events
                self._cached_at = time.time()
                self._last_error = None
            except Exception as exc:
                logger.warning("Economic calendar refresh failed: %s", exc)
                self._last_error = str(exc)
                # Do not refresh the cache timestamp on failure. Existing events can remain
                # visible, but status() will report provider_error and will not claim SAFE.
            return list(self._events)

    def upcoming(self, hours: int = 24, symbol: str | None = None) -> list[dict[str, Any]]:
        events = self.refresh()
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=max(1, min(int(hours), 168)))
        currencies = self._symbol_currencies(symbol)
        result = []
        for event in events:
            event_time = datetime.fromisoformat(event["time"])
            if not (now - timedelta(minutes=self.embargo_after_minutes) <= event_time <= end):
                continue
            if currencies and event.get("currency") and event["currency"] not in currencies:
                continue
            result.append(event)
        return result

    def status(self, symbol: str | None = None) -> dict[str, Any]:
        if not self.configured:
            return {
                "configured": False,
                "active": False,
                "safe": False,
                "provider": self.provider,
                "provider_error": None,
                "message": "Economic calendar provider not configured.",
                "embargo_before_minutes": self.embargo_before_minutes,
                "embargo_after_minutes": self.embargo_after_minutes,
                "blocking_events": [],
            }

        events = self.refresh()
        if self._last_error:
            return {
                "configured": True,
                "active": False,
                "safe": False,
                "provider": self.provider,
                "provider_error": self._last_error,
                "message": "Economic calendar provider is unavailable; News Guard cannot assert a safe window.",
                "embargo_before_minutes": self.embargo_before_minutes,
                "embargo_after_minutes": self.embargo_after_minutes,
                "blocking_events": [],
            }

        now = datetime.now(timezone.utc)
        currencies = self._symbol_currencies(symbol)
        blocking = []
        for event in events:
            if event.get("impact") != "HIGH":
                continue
            if currencies and event.get("currency") and event["currency"] not in currencies:
                continue
            event_time = datetime.fromisoformat(event["time"])
            window_start = event_time - timedelta(minutes=self.embargo_before_minutes)
            window_end = event_time + timedelta(minutes=self.embargo_after_minutes)
            if window_start <= now <= window_end:
                blocking.append(event)

        return {
            "configured": True,
            "active": bool(blocking),
            "safe": not blocking,
            "provider": self.provider,
            "provider_error": None,
            "message": (
                "High-impact economic news embargo is active."
                if blocking
                else "No matching high-impact event is inside the configured embargo window."
            ),
            "embargo_before_minutes": self.embargo_before_minutes,
            "embargo_after_minutes": self.embargo_after_minutes,
            "blocking_events": blocking,
        }
