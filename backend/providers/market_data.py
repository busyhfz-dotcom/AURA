"""Unified market data facade routing each symbol to the right provider."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from config import Settings
from providers.binance_provider import BinanceProvider
from providers.forex_provider import ForexProvider

FOREX_METAL_SYMBOLS = {"XAUUSD", "XAGUSD"}


def classify_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    if symbol.endswith("USDT") or symbol.endswith("BUSD") or symbol in {"BTCUSD", "ETHUSD"}:
        return "CRYPTO"
    if symbol in FOREX_METAL_SYMBOLS:
        return "METALS"
    if len(symbol) == 6 and symbol.isalpha():
        return "FOREX"
    return "UNKNOWN"


class MarketDataHub:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.binance = BinanceProvider()
        self.forex = ForexProvider(settings.forex_provider, settings.forex_api_key)
        self.watchlist = list(settings.crypto_watchlist) + list(settings.forex_watchlist)

    def provider_for(self, symbol: str):
        asset_class = classify_symbol(symbol)
        if asset_class == "CRYPTO":
            return self.binance, asset_class
        return self.forex, asset_class

    def get_candles(self, symbol: str, interval: str = "15m", limit: int = 200) -> tuple[pd.DataFrame, str, str]:
        provider, asset_class = self.provider_for(symbol)
        df = provider.get_candles(symbol, interval=interval, limit=limit)
        source = "BINANCE" if asset_class == "CRYPTO" else ("TWELVEDATA" if self.forex.configured else "NOT_CONFIGURED")
        return df, source, asset_class

    def get_snapshot(self, symbol: str) -> Optional[dict[str, Any]]:
        provider, asset_class = self.provider_for(symbol)
        if asset_class == "CRYPTO":
            return provider.get_ticker_24h(symbol)
        return provider.get_quote(symbol)

    def data_status(self) -> dict[str, Any]:
        return {
            "crypto": {
                "provider": "Binance (public, no key required)",
                "healthy": self.binance.healthy,
                "last_error": self.binance.last_error,
            },
            "forex": self.forex.status(),
        }
