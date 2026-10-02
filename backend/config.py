import os
from dataclasses import dataclass, field
from typing import Optional


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(low, min(value, high))


def _float_env(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(low, min(value, high))


def _list_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


CRYPTO_WATCHLIST_DEFAULT = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
]
FOREX_WATCHLIST_DEFAULT = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "XAUUSD",
]


@dataclass(frozen=True)
class Settings:
    brand_name: str
    cors_origins: list[str]
    database_path: str

    crypto_watchlist: list[str]
    forex_watchlist: list[str]

    forex_provider: Optional[str]
    forex_api_key: Optional[str]

    economic_calendar_provider: Optional[str]
    economic_calendar_api_key: Optional[str]
    news_embargo_before_minutes: int
    news_embargo_after_minutes: int

    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]

    scan_interval_seconds: int
    analysis_interval_seconds: int
    high_volatility_threshold_percent: float
    high_risk_score_threshold: int


def load_settings() -> Settings:
    origins = [
        origin.strip()
        for origin in os.getenv(
            "VERTEX_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ]

    forex_provider = (os.getenv("VERTEX_FOREX_PROVIDER") or "").strip().lower() or None
    economic_provider = (os.getenv("VERTEX_ECONOMIC_CALENDAR_PROVIDER") or "").strip().lower() or None

    return Settings(
        brand_name=os.getenv("VERTEX_BRAND_NAME", "VERTEX"),
        cors_origins=origins,
        database_path=os.getenv("VERTEX_DATABASE_PATH", "./data/vertex.db"),
        crypto_watchlist=_list_env("VERTEX_CRYPTO_WATCHLIST", CRYPTO_WATCHLIST_DEFAULT),
        forex_watchlist=_list_env("VERTEX_FOREX_WATCHLIST", FOREX_WATCHLIST_DEFAULT),
        forex_provider=forex_provider,
        forex_api_key=os.getenv("VERTEX_FOREX_API_KEY") or None,
        economic_calendar_provider=economic_provider,
        economic_calendar_api_key=os.getenv("VERTEX_ECONOMIC_CALENDAR_API_KEY") or None,
        news_embargo_before_minutes=_int_env("VERTEX_NEWS_EMBARGO_BEFORE_MINUTES", 30, 0, 240),
        news_embargo_after_minutes=_int_env("VERTEX_NEWS_EMBARGO_AFTER_MINUTES", 15, 0, 240),
        telegram_bot_token=os.getenv("VERTEX_TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("VERTEX_TELEGRAM_CHAT_ID") or None,
        scan_interval_seconds=_int_env("VERTEX_SCAN_INTERVAL_SECONDS", 20, 5, 300),
        analysis_interval_seconds=_int_env("VERTEX_ANALYSIS_INTERVAL_SECONDS", 120, 30, 900),
        high_volatility_threshold_percent=_float_env("VERTEX_HIGH_VOLATILITY_THRESHOLD_PERCENT", 1.5, 0.1, 20.0),
        high_risk_score_threshold=_int_env("VERTEX_HIGH_RISK_SCORE_THRESHOLD", 70, 10, 100),
    )
