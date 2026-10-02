"""Forex/metals market data adapter.

Real intraday forex data without any account is not available anywhere —
every legitimate provider requires at least a free API key. This adapter
follows the same no-fabrication rule as the rest of the platform: until a
provider + key is configured, it returns an explicit NOT_CONFIGURED state
and never invents a price. Currently wired for Twelve Data (twelvedata.com),
which has a free tier (no credit card), but that tier caps out at 8 requests/
minute — easy to blow through since both the fast scan loop and the deeper
Trade Desk analysis loop hit this provider independently, each across
several symbols/timeframes in a tight burst.

Two mechanisms keep this under the free-tier ceiling instead of just hoping
interval tuning is enough:

1. A shared token-bucket rate limiter (`_throttle`) that makes every caller
   (candles or quote, scan loop or analysis loop) wait its turn rather than
   fire immediately — so a burst of calls gets spaced out across the 60s
   window instead of all landing at once and tripping a 429.
2. Negative caching: a failed request (429, network error, etc.) is now
   remembered for `cache_seconds` just like a success, instead of being
   retried on every single call that happens to land while the API is
   already over quota. Without this, one bad burst meant every subsequent
   caller kept re-attempting immediately, which is what turned a transient
   429 into a permanent one in practice.

If you still see 429s in /api/health after this, trim VERTEX_FOREX_WATCHLIST
and/or raise VERTEX_SCAN_INTERVAL_SECONDS / VERTEX_ANALYSIS_INTERVAL_SECONDS
further — but the throttle below should make that a tuning knob rather than
a hard requirement.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Optional

import pandas as pd
import requests

logger = logging.getLogger("VertexForexProvider")

TWELVEDATA_BASE_URL = "https://api.twelvedata.com"

_INTERVAL_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "4h": "4h", "1d": "1day",
}


def _to_provider_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    if "/" in symbol:
        return symbol
    if len(symbol) == 6:
        return f"{symbol[:3]}/{symbol[3:]}"
    if symbol == "XAUUSD":
        return "XAU/USD"
    if symbol == "XAGUSD":
        return "XAG/USD"
    return symbol


class _RateLimiter:
    """Blocking token-bucket: at most `max_calls` calls per `period` seconds,
    shared across every thread hitting this provider. Callers run inside
    asyncio.to_thread, so blocking here is fine — it never stalls the event
    loop, just the one worker thread making the request.
    """

    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self._lock = threading.Lock()
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.time()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                wait_for = self.period - (now - self._calls[0]) + 0.05
            if wait_for > 0:
                time.sleep(wait_for)


class ForexProvider:
    asset_class = "FOREX"

    def __init__(self, provider: Optional[str], api_key: Optional[str], timeout: float = 8.0, cache_seconds: float = 60.0):
        self.provider = (provider or "").strip().lower() or None
        self.api_key = api_key or None
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._lock = threading.RLock()
        self._kline_cache: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}
        self._quote_cache: dict[str, tuple[float, dict]] = {}
        # Tracks the last *attempt* (success or failure) per cache key, separate
        # from the success-only caches above, so a failing key backs off for
        # cache_seconds instead of being retried on every call that lands
        # while the free-tier quota is already exhausted.
        self._last_attempt: dict[tuple[str, ...], float] = {}
        self._last_error: Optional[str] = None
        # Twelve Data's free tier allows 8 requests/minute; leave a safety
        # margin below that so timing jitter doesn't tip us over.
        self._throttle = _RateLimiter(max_calls=7, period=60.0)

    @property
    def configured(self) -> bool:
        return self.provider == "twelvedata" and bool(self.api_key)

    @property
    def healthy(self) -> bool:
        return self.configured and self._last_error is None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def status(self) -> dict[str, Any]:
        if not self.configured:
            return {
                "configured": False,
                "provider": self.provider,
                "message": "Forex data provider is not configured. Set VERTEX_FOREX_PROVIDER=twelvedata and VERTEX_FOREX_API_KEY.",
            }
        return {
            "configured": True,
            "provider": self.provider,
            "healthy": self._last_error is None,
            "last_error": self._last_error,
        }

    def _should_attempt(self, attempt_key: tuple[str, ...]) -> bool:
        """False if this exact request failed within the last cache_seconds —
        prevents hammering an already-rate-limited or erroring endpoint."""
        with self._lock:
            last = self._last_attempt.get(attempt_key)
        return not (last and time.time() - last < self.cache_seconds)

    def _mark_attempt(self, attempt_key: tuple[str, ...]) -> None:
        with self._lock:
            self._last_attempt[attempt_key] = time.time()

    def get_candles(self, symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
        if not self.configured:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        provider_symbol = _to_provider_symbol(symbol)
        cache_key = (provider_symbol, interval, limit)
        with self._lock:
            cached = self._kline_cache.get(cache_key)
            if cached and time.time() - cached[0] < self.cache_seconds:
                return cached[1].copy()

        attempt_key = ("candles",) + cache_key
        if not self._should_attempt(attempt_key):
            # Recently failed (likely 429) — return whatever we have cached
            # rather than firing another doomed request into the same quota.
            with self._lock:
                cached = self._kline_cache.get(cache_key)
            return cached[1].copy() if cached else pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        self._throttle.acquire()
        self._mark_attempt(attempt_key)
        try:
            response = requests.get(
                f"{TWELVEDATA_BASE_URL}/time_series",
                params={
                    "symbol": provider_symbol,
                    "interval": _INTERVAL_MAP.get(interval, "15min"),
                    "outputsize": min(limit, 500),
                    "apikey": self.api_key,
                    "order": "ASC",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("status") == "error":
                raise RuntimeError(payload.get("message", "Twelve Data returned an error."))
            values = payload.get("values") if isinstance(payload, dict) else None
            if not values:
                raise RuntimeError("Twelve Data returned no candles for this symbol.")

            df = pd.DataFrame(values)
            df["time"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
            for column in ("open", "high", "low", "close"):
                df[column] = pd.to_numeric(df[column], errors="coerce")
            df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0.0)
            df = df[["time", "open", "high", "low", "close", "volume"]].dropna(
                subset=["time", "open", "high", "low", "close"]
            ).sort_values("time").reset_index(drop=True)

            with self._lock:
                self._kline_cache[cache_key] = (time.time(), df)
            self._last_error = None
            return df.copy()
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Twelve Data candles fetch failed for %s: %s", symbol, exc)
            with self._lock:
                cached = self._kline_cache.get(cache_key)
            if cached:
                return cached[1].copy()
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    @staticmethod
    def snapshot_from_candles(symbol: str, df: pd.DataFrame) -> Optional[dict[str, Any]]:
        """Derive a quote-like snapshot from already-fetched candle data
        instead of spending a separate Twelve Data /quote request. Scheduler
        already pulls candles every cycle for signal/risk analysis, so this
        keeps the live-price display "free" instead of doubling call volume.
        """
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        first = df.iloc[0]
        last_price = float(last["close"])
        first_price = float(first["close"])
        change = last_price - first_price
        change_percent = (change / first_price * 100.0) if first_price else 0.0
        return {
            "symbol": symbol.upper(),
            "last_price": last_price,
            "price_change": change,
            "price_change_percent": change_percent,
            "high_24h": float(df["high"].max()),
            "low_24h": float(df["low"].min()),
        }

    def get_quote(self, symbol: str) -> Optional[dict[str, Any]]:
        if not self.configured:
            return None
        provider_symbol = _to_provider_symbol(symbol)
        with self._lock:
            cached = self._quote_cache.get(provider_symbol)
            if cached and time.time() - cached[0] < self.cache_seconds:
                return cached[1]

        attempt_key = ("quote", provider_symbol)
        if not self._should_attempt(attempt_key):
            with self._lock:
                cached = self._quote_cache.get(provider_symbol)
            return cached[1] if cached else None

        self._throttle.acquire()
        self._mark_attempt(attempt_key)
        try:
            response = requests.get(
                f"{TWELVEDATA_BASE_URL}/quote",
                params={"symbol": provider_symbol, "apikey": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("status") == "error":
                raise RuntimeError(payload.get("message", "Twelve Data returned an error."))
            result = {
                "symbol": symbol.upper(),
                "last_price": float(payload["close"]),
                "price_change": float(payload.get("change", 0.0) or 0.0),
                "price_change_percent": float(payload.get("percent_change", 0.0) or 0.0),
                "high_24h": float(payload.get("high", payload["close"])),
                "low_24h": float(payload.get("low", payload["close"])),
            }
            with self._lock:
                self._quote_cache[provider_symbol] = (time.time(), result)
            self._last_error = None
            return result
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Twelve Data quote fetch failed for %s: %s", symbol, exc)
            with self._lock:
                cached = self._quote_cache.get(provider_symbol)
            return cached[1] if cached else None
