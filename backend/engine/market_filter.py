from datetime import datetime, timezone
from typing import Optional

from news_guard import NewsGuardService


class MarketFilter:
    def __init__(self, news_guard: Optional[NewsGuardService] = None):
        self.news_guard = news_guard

    @staticmethod
    def get_current_session() -> str:
        hour = datetime.now(timezone.utc).hour
        if 7 <= hour < 12:
            return "London Session"
        if 12 <= hour < 16:
            return "London / New York Overlap"
        if 16 <= hour < 20:
            return "New York PM"
        if 0 <= hour < 7:
            return "Asia Session"
        return "Off-Peak"

    def news_guard_status(
        self,
        symbol: Optional[str] = None,
        include_events: bool = False,
        refresh: bool = True,
    ) -> dict:
        if self.news_guard is None:
            return {
                "configured": False,
                "healthy": False,
                "active": False,
                "blocking": False,
                "provider": None,
                "symbol": symbol,
                "message": "Economic calendar provider not configured.",
                "events": [],
                "active_events": [],
                "next_event": None,
            }
        return self.news_guard.status(symbol=symbol, include_events=include_events, refresh=refresh)

    def is_news_embargo_active(self, symbol: Optional[str] = None) -> bool:
        return bool(self.news_guard_status(symbol=symbol)["active"])

    def is_execution_blocked_by_news(self, symbol: Optional[str] = None) -> bool:
        return bool(self.news_guard_status(symbol=symbol)["blocking"])
