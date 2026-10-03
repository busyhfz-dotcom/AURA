"""Optional Telegram push channel for 24/7 alerts, so notifications reach the
operator even when the dashboard isn't open. No-ops honestly when unconfigured.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger("VertexTelegramNotifier")


class TelegramNotifier:
    def __init__(self, bot_token: Optional[str], chat_id: Optional[str], timeout: float = 6.0):
        self.bot_token = bot_token or None
        self.chat_id = chat_id or None
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.configured:
            return False
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            error = str(exc).replace(self.bot_token, "***") if self.bot_token else str(exc)
            logger.warning("Telegram push failed: %s", error)
            return False
