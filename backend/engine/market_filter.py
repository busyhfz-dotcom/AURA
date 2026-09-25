from datetime import datetime, timezone


class MarketFilter:
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

    @staticmethod
    def news_guard_status() -> dict:
        # Intentionally explicit: a real economic-calendar provider has not been wired yet.
        # Live auto-execution must stay disabled until that integration exists.
        return {
            "configured": False,
            "active": False,
            "provider": None,
            "message": "Economic calendar provider not configured.",
        }

    @classmethod
    def is_news_embargo_active(cls) -> bool:
        return bool(cls.news_guard_status()["active"])
