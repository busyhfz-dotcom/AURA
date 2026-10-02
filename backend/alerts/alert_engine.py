"""Turns scan results into deduplicated, cooldown-limited alerts.

Every scan produces a fresh risk score and signal status, but we only want
to *alert* on meaningful transitions (entering high risk, a new validated
setup, an active news embargo) — not repeat the same alert every N seconds.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from alerts.telegram_notifier import TelegramNotifier
from storage.db import VertexStore


class AlertEngine:
    def __init__(self, store: VertexStore, notifier: TelegramNotifier, cooldown_seconds: int = 900):
        self.store = store
        self.notifier = notifier
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.RLock()
        self._last_fired: dict[tuple[str, str], float] = {}
        self._last_setup_key: dict[str, Optional[str]] = {}
        self._last_recommendation: dict[str, str] = {}

    def _should_fire(self, symbol: str, category: str) -> bool:
        key = (symbol, category)
        now = time.time()
        with self._lock:
            last = self._last_fired.get(key)
            if last is not None and now - last < self.cooldown_seconds:
                return False
            self._last_fired[key] = now
        return True

    def evaluate(self, symbol: str, asset_class: str, risk: dict[str, Any], signal: dict[str, Any]) -> list[dict[str, Any]]:
        fired: list[dict[str, Any]] = []

        if risk["risk_label"] == "HIGH" and self._should_fire(symbol, "RISK_HIGH"):
            title = f"{symbol}: HIGH risk conditions"
            message = "; ".join(risk.get("reasons") or []) or "Composite risk score crossed the HIGH threshold."
            alert_id = self.store.add_alert(symbol, asset_class, "RISK", "HIGH", title, message, metadata=risk)
            fired.append({"id": alert_id, "category": "RISK", "severity": "HIGH", "title": title, "message": message})

        if risk.get("news_embargo_active") and self._should_fire(symbol, "NEWS_EMBARGO"):
            title = f"{symbol}: high-impact news window active"
            message = "A high-impact economic release is inside its embargo window for this symbol's currencies."
            alert_id = self.store.add_alert(symbol, asset_class, "NEWS", "MEDIUM", title, message, metadata=risk)
            fired.append({"id": alert_id, "category": "NEWS", "severity": "MEDIUM", "title": title, "message": message})

        setup_key = None
        if signal.get("status") == "A_PLUS_SETUP":
            setup_key = f"{signal.get('action')}:{signal.get('entry')}:{signal.get('sl')}:{signal.get('tp')}"
        with self._lock:
            previous_key = self._last_setup_key.get(symbol)
            self._last_setup_key[symbol] = setup_key
        if setup_key and setup_key != previous_key:
            title = f"{symbol}: validated {signal.get('action')} structure ({signal.get('confluence_score')}/100)"
            message = (
                f"Entry {signal.get('entry')} · SL {signal.get('sl')} · TP {signal.get('tp')} · "
                f"session {signal.get('session')}. This is a structural read, not investment advice."
            )
            self.store.add_signal_event(signal, asset_class)
            alert_id = self.store.add_alert(symbol, asset_class, "SETUP", "INFO", title, message, metadata=signal)
            fired.append({"id": alert_id, "category": "SETUP", "severity": "INFO", "title": title, "message": message})
        elif signal.get("status") in {"SCANNING", "WAITING_FOR_DATA"}:
            # Still log non-setup scans occasionally isn't necessary; only setups are logged as events
            # to keep the table meaningful, but we log status transitions away from a setup once.
            pass

        for item in fired:
            severity_emoji = {"HIGH": "\U0001F534", "MEDIUM": "\U0001F7E1", "INFO": "\U0001F7E2"}.get(item["severity"], "⚪")
            self.notifier.send(f"{severity_emoji} <b>{item['title']}</b>\n{item['message']}")

        return fired

    def evaluate_trade_call(self, symbol: str, asset_class: str, analysis: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Fires (and persists) a trade call only when the recommendation actually
        transitions into or out of BUY/SELL, so a steady WAIT or a steady BUY
        doesn't spam a new alert every analysis cycle."""
        recommendation = analysis["recommendation"]
        with self._lock:
            previous = self._last_recommendation.get(symbol)
            self._last_recommendation[symbol] = recommendation

        if recommendation == previous:
            return None
        if recommendation not in {"BUY", "SELL"}:
            return None

        self.store.add_trade_call(analysis, asset_class)
        entry_plan = analysis.get("entry_plan") or {}
        title = f"{symbol}: {recommendation} call — {analysis['probability_percent']}% confluence"
        message = (
            f"Suggested risk {analysis['suggested_risk_percent']}% of account. "
            f"Entry {entry_plan.get('entry', '—')} · SL {entry_plan.get('sl', '—')} · TP {entry_plan.get('tp', '—')}. "
            f"{analysis['disclaimer']}"
        )
        alert_id = self.store.add_alert(symbol, asset_class, "TRADE_CALL", "INFO", title, message, metadata=analysis)
        result = {"id": alert_id, "category": "TRADE_CALL", "severity": "INFO", "title": title, "message": message}
        severity_emoji = "\U0001F7E2" if recommendation == "BUY" else "\U0001F534"
        self.notifier.send(f"{severity_emoji} <b>{title}</b>\n{message}")
        return result
