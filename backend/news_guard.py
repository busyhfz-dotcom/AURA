import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import requests

from config import Settings

logger = logging.getLogger("NewsGuard")

COUNTRY_CURRENCY = {
    "united states": "USD",
    "euro area": "EUR",
    "united kingdom": "GBP",
    "japan": "JPY",
    "canada": "CAD",
    "australia": "AUD",
    "new zealand": "NZD",
    "switzerland": "CHF",
}

KNOWN_CURRENCIES = set(COUNTRY_CURRENCY.values())


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_provider_date(value: object) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    return _utc(parsed)


def currencies_for_symbol(symbol: str) -> set[str]:
    symbol = symbol.upper().strip()
    if len(symbol) == 6 and symbol[:3] in KNOWN_CURRENCIES and symbol[3:] in KNOWN_CURRENCIES:
        return {symbol[:3], symbol[3:]}
    if symbol in {"XAUUSD", "BTCUSD", "ETHUSD", "NAS100", "SP500", "USOIL"}:
        return {"USD"}
    if symbol.endswith("USD"):
        return {"USD"}
    return set()


class TradingEconomicsCalendar:
    provider_name = "Trading Economics"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.trading_economics_api_key
        self.countries = settings.news_countries
        self.min_importance = settings.news_min_importance
        self.cache_seconds = settings.news_cache_seconds
        self._lock = threading.RLock()
        self._cache: list[dict] = []
        self._cache_key: tuple[str, str] | None = None
        self._cache_at = 0.0

    @property
    def configured(self) -> bool:
        return self.settings.news_provider == "tradingeconomics" and bool(self.api_key)

    def _fetch_country(self, country: str, start_date: str, end_date: str) -> list[dict]:
        encoded_country = quote(country, safe="")
        url = (
            "https://api.tradingeconomics.com/calendar/country/"
            f"{encoded_country}/{start_date}/{end_date}"
        )
        response = requests.get(
            url,
            params={
                "c": self.api_key,
                "importance": self.min_importance,
                "values": "true",
                "f": "json",
            },
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Trading Economics returned an unexpected calendar payload.")
        return payload

    @staticmethod
    def _normalize(item: dict) -> Optional[dict]:
        event_time = _parse_provider_date(item.get("Date"))
        if event_time is None:
            return None
        country = str(item.get("Country") or "").strip()
        currency = COUNTRY_CURRENCY.get(country.lower())
        importance_raw = item.get("Importance")
        try:
            importance = int(importance_raw)
        except (TypeError, ValueError):
            importance = 0
        return {
            "id": str(item.get("CalendarId") or item.get("CalendarID") or ""),
            "date": event_time.isoformat(),
            "country": country,
            "currency": currency,
            "category": str(item.get("Category") or "").strip(),
            "event": str(item.get("Event") or item.get("Category") or "").strip(),
            "importance": importance,
            "actual": item.get("Actual"),
            "previous": item.get("Previous"),
            "forecast": item.get("Forecast"),
            "te_forecast": item.get("TEForecast"),
            "source": str(item.get("Source") or "").strip(),
            "date_confirmed": str(item.get("DateSpan") or "0") == "0",
        }

    def fetch_events(self, now: Optional[datetime] = None, days: int = 2) -> list[dict]:
        if not self.configured:
            raise RuntimeError("Trading Economics calendar is not configured.")

        now = _utc(now or datetime.now(timezone.utc))
        start = (now - timedelta(days=1)).date().isoformat()
        end = (now + timedelta(days=max(1, min(days, 7)))).date().isoformat()
        cache_key = (start, end)

        with self._lock:
            if (
                self._cache_key == cache_key
                and self._cache
                and time.monotonic() - self._cache_at < self.cache_seconds
            ):
                return list(self._cache)

        raw_events: list[dict] = []
        errors: list[str] = []
        for country in self.countries:
            try:
                raw_events.extend(self._fetch_country(country, start, end))
            except Exception as exc:
                logger.warning("Calendar request failed for %s: %s", country, exc)
                errors.append(country)

        if errors:
            raise RuntimeError(
                "Economic calendar provider failed for configured markets: "
                + ", ".join(errors)
            )

        normalized: list[dict] = []
        seen: set[str] = set()
        for item in raw_events:
            event = self._normalize(item)
            if event is None or event["importance"] < self.min_importance:
                continue
            dedupe = event["id"] or f'{event["country"]}:{event["date"]}:{event["event"]}'
            if dedupe in seen:
                continue
            seen.add(dedupe)
            normalized.append(event)

        normalized.sort(key=lambda event: event["date"])
        with self._lock:
            self._cache = normalized
            self._cache_key = cache_key
            self._cache_at = time.monotonic()
        return list(normalized)


class NewsGuardService:
    def __init__(self, settings: Settings, provider: Optional[TradingEconomicsCalendar] = None):
        self.settings = settings
        self.provider = provider or TradingEconomicsCalendar(settings)

    def status(
        self,
        symbol: Optional[str] = None,
        now: Optional[datetime] = None,
        include_events: bool = True,
    ) -> dict:
        now = _utc(now or datetime.now(timezone.utc))
        if not self.provider.configured:
            return {
                "configured": False,
                "healthy": False,
                "active": False,
                "blocking": False,
                "provider": self.provider.provider_name,
                "symbol": symbol,
                "currencies": sorted(currencies_for_symbol(symbol or "")),
                "message": "Economic calendar provider not configured.",
                "events": [],
                "active_events": [],
                "next_event": None,
            }

        try:
            events = self.provider.fetch_events(now=now)
        except Exception as exc:
            logger.error("Economic calendar unavailable: %s", exc)
            return {
                "configured": True,
                "healthy": False,
                "active": False,
                "blocking": True,
                "provider": self.provider.provider_name,
                "symbol": symbol,
                "currencies": sorted(currencies_for_symbol(symbol or "")),
                "message": "Economic calendar provider is unavailable; live execution fails closed.",
                "error": str(exc),
                "events": [],
                "active_events": [],
                "next_event": None,
            }

        impacted = currencies_for_symbol(symbol or "")
        relevant = [
            event
            for event in events
            if not impacted or (event.get("currency") and event["currency"] in impacted)
        ]
        before = timedelta(minutes=self.settings.news_block_before_minutes)
        after = timedelta(minutes=self.settings.news_block_after_minutes)
        active_events = []
        future_events = []

        for event in relevant:
            event_time = _parse_provider_date(event.get("date"))
            if event_time is None:
                continue
            if event_time - before <= now <= event_time + after:
                active_events.append(event)
            if event_time > now:
                future_events.append(event)

        next_event = min(future_events, key=lambda event: event["date"]) if future_events else None
        active = bool(active_events)
        if active:
            message = "High-impact economic-news embargo is active for this market."
        elif next_event:
            message = "News Guard operational; next relevant high-impact event is scheduled."
        else:
            message = "News Guard operational; no relevant high-impact event is scheduled in the provider window."

        return {
            "configured": True,
            "healthy": True,
            "active": active,
            "blocking": active,
            "provider": self.provider.provider_name,
            "symbol": symbol,
            "currencies": sorted(impacted),
            "message": message,
            "block_before_minutes": self.settings.news_block_before_minutes,
            "block_after_minutes": self.settings.news_block_after_minutes,
            "events": relevant if include_events else [],
            "active_events": active_events,
            "next_event": next_event,
        }
