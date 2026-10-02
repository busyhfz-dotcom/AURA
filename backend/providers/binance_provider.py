"""Live crypto market data from Binance's public REST API.

No API key is required for market data endpoints. This provider never
fabricates candles: if Binance is unreachable or returns bad data, callers
receive an explicit error/empty result instead of invented prices.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import pandas as pd
import requests

logger = logging.getLogger("VertexBinanceProvider")

BASE_URL = "https://api.binance.com"


class BinanceProvider:
    asset_class = "CRYPTO"

    def __init__(self, timeout: float = 8.0, cache_seconds: float = 5.0):
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._lock = threading.RLock()
        self._kline_cache: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}
        self._ticker_cache: dict[str, tuple[float, dict]] = {}
        self._last_error: Optional[str] = None

    @property
    def healthy(self) -> bool:
        return self._last_error is None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def get_candles(self, symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
        symbol = symbol.upper().strip()
        cache_key = (symbol, interval, limit)
        with self._lock:
            cached = self._kline_cache.get(cache_key)
            if cached and time.time() - cached[0] < self.cache_seconds:
                return cached[1].copy()

        try:
            response = requests.get(
                f"{BASE_URL}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise RuntimeError("Unexpected Binance klines payload shape.")

            df = pd.DataFrame(
                rows,
                columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
                ],
            )
            df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            for column in ("open", "high", "low", "close", "volume"):
                df[column] = pd.to_numeric(df[column], errors="coerce")
            df = df[["time", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)

            with self._lock:
                self._kline_cache[cache_key] = (time.time(), df)
            self._last_error = None
            return df.copy()
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Binance klines fetch failed for %s: %s", symbol, exc)
            with self._lock:
                cached = self._kline_cache.get(cache_key)
            if cached:
                # Serve last-known-good data rather than a fabricated candle, but the
                # caller can see last_error and knows this is stale.
                return cached[1].copy()
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    def get_ticker_24h(self, symbol: str) -> Optional[dict[str, Any]]:
        symbol = symbol.upper().strip()
        with self._lock:
            cached = self._ticker_cache.get(symbol)
            if cached and time.time() - cached[0] < self.cache_seconds:
                return cached[1]

        try:
            response = requests.get(
                f"{BASE_URL}/api/v3/ticker/24hr",
                params={"symbol": symbol},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            result = {
                "symbol": symbol,
                "last_price": float(payload["lastPrice"]),
                "price_change": float(payload["priceChange"]),
                "price_change_percent": float(payload["priceChangePercent"]),
                "high_24h": float(payload["highPrice"]),
                "low_24h": float(payload["lowPrice"]),
                "volume_24h": float(payload["volume"]),
                "quote_volume_24h": float(payload["quoteVolume"]),
                "trades_24h": int(payload["count"]),
            }
            with self._lock:
                self._ticker_cache[symbol] = (time.time(), result)
            self._last_error = None
            return result
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Binance 24hr ticker fetch failed for %s: %s", symbol, exc)
            with self._lock:
                cached = self._ticker_cache.get(symbol)
            return cached[1] if cached else None
