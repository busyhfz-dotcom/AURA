import os
from dataclasses import dataclass
from typing import Optional


def _optional_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


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


@dataclass(frozen=True)
class Settings:
    execution_mode: str
    mt5_account: Optional[int]
    mt5_password: Optional[str]
    mt5_server: Optional[str]
    cors_origins: list[str]
    default_symbol: str
    max_risk_percent: float
    mt5_deviation: int
    database_path: str
    paper_starting_balance: float
    max_open_positions: int
    max_trades_per_day: int
    max_daily_loss_percent: float
    execution_api_key: Optional[str]
    economic_calendar_provider: Optional[str]
    economic_calendar_api_key: Optional[str]
    news_embargo_before_minutes: int
    news_embargo_after_minutes: int
    live_execution_transport: str
    execution_worker_url: Optional[str]
    execution_worker_secret: Optional[str]
    execution_worker_timeout_seconds: int
    autopilot_shared_secret: Optional[str]
    autopilot_heartbeat_ttl_seconds: int

    @property
    def live_execution_enabled(self) -> bool:
        return self.execution_mode == "live"

    @property
    def execution_worker_configured(self) -> bool:
        return bool(self.execution_worker_url and self.execution_worker_secret)


def load_settings() -> Settings:
    raw_mode = os.getenv("AURA_EXECUTION_MODE", "paper").strip().lower()
    execution_mode = raw_mode if raw_mode in {"paper", "live"} else "paper"

    origins = [
        origin.strip()
        for origin in os.getenv(
            "AURA_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ]

    return Settings(
        execution_mode=execution_mode,
        mt5_account=_optional_int(os.getenv("MT5_ACCOUNT")),
        mt5_password=os.getenv("MT5_PASSWORD") or None,
        mt5_server=os.getenv("MT5_SERVER") or None,
        cors_origins=origins,
        default_symbol=os.getenv("AURA_DEFAULT_SYMBOL", "EURUSD").upper(),
        max_risk_percent=_float_env("AURA_MAX_RISK_PERCENT", 1.0, 0.1, 2.0),
        mt5_deviation=_int_env("AURA_MT5_DEVIATION", 20, 1, 100),
        database_path=os.getenv("AURA_DATABASE_PATH", "./data/aura.db"),
        paper_starting_balance=_float_env("AURA_PAPER_STARTING_BALANCE", 10_000.0, 100.0, 100_000_000.0),
        max_open_positions=_int_env("AURA_MAX_OPEN_POSITIONS", 3, 1, 20),
        max_trades_per_day=_int_env("AURA_MAX_TRADES_PER_DAY", 8, 1, 100),
        max_daily_loss_percent=_float_env("AURA_MAX_DAILY_LOSS_PERCENT", 2.0, 0.25, 20.0),
        execution_api_key=os.getenv("AURA_EXECUTION_API_KEY") or None,
        economic_calendar_provider=(os.getenv("AURA_ECONOMIC_CALENDAR_PROVIDER") or "").strip().lower() or None,
        economic_calendar_api_key=os.getenv("AURA_ECONOMIC_CALENDAR_API_KEY") or None,
        news_embargo_before_minutes=_int_env("AURA_NEWS_EMBARGO_BEFORE_MINUTES", 30, 0, 240),
        news_embargo_after_minutes=_int_env("AURA_NEWS_EMBARGO_AFTER_MINUTES", 15, 0, 240),
        live_execution_transport=(os.getenv("AURA_LIVE_EXECUTION_TRANSPORT", "worker").strip().lower() or "worker"),
        execution_worker_url=(os.getenv("AURA_EXECUTION_WORKER_URL") or "").strip().rstrip("/") or None,
        execution_worker_secret=os.getenv("AURA_EXECUTION_WORKER_SECRET") or None,
        execution_worker_timeout_seconds=_int_env("AURA_EXECUTION_WORKER_TIMEOUT_SECONDS", 10, 2, 60),
        autopilot_shared_secret=os.getenv("AURA_AUTOPILOT_SHARED_SECRET") or None,
        autopilot_heartbeat_ttl_seconds=_int_env("AURA_AUTOPILOT_HEARTBEAT_TTL_SECONDS", 90, 30, 600),
    )
