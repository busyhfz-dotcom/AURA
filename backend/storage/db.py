import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VertexStore:
    """Durable store for alerts, signal events and risk snapshots.

    SQLite/WAL keeps this simple to self-host; the query surface is narrow
    enough to move to Postgres later without touching callers.
    """

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signal_events (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    status TEXT NOT NULL,
                    action TEXT,
                    entry REAL,
                    sl REAL,
                    tp REAL,
                    confluence_score INTEGER NOT NULL,
                    session TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS risk_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    risk_score INTEGER NOT NULL,
                    risk_label TEXT NOT NULL,
                    volatility_percent REAL,
                    change_percent_24h REAL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trade_calls (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    probability_percent REAL NOT NULL,
                    suggested_risk_percent REAL NOT NULL,
                    entry REAL,
                    sl REAL,
                    tp REAL,
                    basis TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_candles (
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    source TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    open_time TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    PRIMARY KEY (symbol, timeframe, open_time)
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
                CREATE INDEX IF NOT EXISTS idx_signal_events_created_at ON signal_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_risk_snapshots_created_at ON risk_snapshots(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_risk_snapshots_symbol ON risk_snapshots(symbol);
                CREATE INDEX IF NOT EXISTS idx_trade_calls_created_at ON trade_calls(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_market_candles_lookup ON market_candles(symbol, timeframe, open_time DESC);
                """
            )

    def add_closed_candles(self, symbol: str, asset_class: str, source: str, timeframe: str, candles: pd.DataFrame) -> int:
        """Archive only completed provider bars; repeated scans never rewrite history."""
        if candles.empty:
            return 0
        interval_seconds = {"15m": 900, "1h": 3600, "4h": 14400}.get(timeframe)
        if interval_seconds is None:
            raise ValueError("Unsupported candle timeframe")
        now = datetime.now(timezone.utc)
        rows = []
        for candle in candles.itertuples(index=False):
            opened = pd.Timestamp(candle.time)
            if opened.tzinfo is None:
                opened = opened.tz_localize("UTC")
            if (now - opened.to_pydatetime()).total_seconds() < interval_seconds:
                continue
            values = (float(candle.open), float(candle.high), float(candle.low), float(candle.close))
            if not all(pd.notna(value) for value in values) or values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
                continue
            volume = float(candle.volume) if hasattr(candle, "volume") and pd.notna(candle.volume) else None
            rows.append((symbol.upper(), asset_class, source, timeframe, opened.isoformat(), *values, volume))
        with self._lock, self._conn:
            cursor = self._conn.executemany(
                """INSERT OR IGNORE INTO market_candles
                   (symbol, asset_class, source, timeframe, open_time, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows,
            )
        return cursor.rowcount

    def historical_candles(self, symbol: str, timeframe: str = "15m", limit: int = 500) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 2000))
        with self._lock:
            rows = self._conn.execute(
                """SELECT symbol, asset_class, source, timeframe, open_time, open, high, low, close, volume
                   FROM market_candles WHERE symbol = ? AND timeframe = ? ORDER BY open_time DESC LIMIT ?""",
                (symbol.upper(), timeframe, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def candles_after(self, symbol: str, open_time: str, limit: int = 120) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT open_time, open, high, low, close FROM market_candles
                   WHERE symbol = ? AND timeframe = '15m' AND open_time >= ?
                   ORDER BY open_time ASC LIMIT ?""",
                (symbol.upper(), open_time, max(1, min(int(limit), 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    def research_readiness(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT asset_class, timeframe, COUNT(*) AS bars, COUNT(DISTINCT symbol) AS symbols,
                          MIN(open_time) AS first_open_time, MAX(open_time) AS last_open_time
                   FROM market_candles GROUP BY asset_class, timeframe ORDER BY asset_class, timeframe"""
            ).fetchall()
        mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
        on_railway = bool(os.getenv("RAILWAY_ENVIRONMENT_ID"))
        persistent = bool(mount and Path(self.path).resolve().is_relative_to(Path(mount).resolve())) if self.path != ":memory:" else False
        return {
            "storage": "PERSISTENT_VOLUME" if persistent else "EPHEMERAL_CONTAINER" if on_railway else "LOCAL_DISK",
            "series": [dict(row) for row in rows],
            "calibrated_probability_available": False,
            "reason": "No independently validated, out-of-sample trade outcomes are available yet.",
        }

    def add_alert(self, symbol: str, asset_class: str, category: str, severity: str, title: str, message: str, metadata: Optional[dict] = None) -> str:
        alert_id = f"ALT-{uuid.uuid4().hex[:12].upper()}"
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO alerts (id, symbol, asset_class, category, severity, title, message, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, symbol, asset_class, category, severity, title, message, json.dumps(metadata or {}), utc_now_iso()),
            )
        return alert_id

    def add_signal_event(self, signal: dict[str, Any], asset_class: str) -> str:
        event_id = f"SIG-{uuid.uuid4().hex[:12].upper()}"
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO signal_events (id, symbol, asset_class, status, action, entry, sl, tp, confluence_score, session, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, signal["symbol"], asset_class, signal["status"], signal.get("action"),
                    signal.get("entry"), signal.get("sl"), signal.get("tp"),
                    int(signal.get("confluence_score", 0)), signal.get("session"), utc_now_iso(),
                ),
            )
        return event_id

    def add_risk_snapshot(self, risk: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO risk_snapshots (symbol, asset_class, risk_score, risk_label, volatility_percent, change_percent_24h, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    risk["symbol"], risk["asset_class"], int(risk["risk_score"]), risk["risk_label"],
                    risk.get("volatility_percent"), risk.get("change_percent_24h"), utc_now_iso(),
                ),
            )

    def add_trade_call(self, analysis: dict[str, Any], asset_class: str) -> str:
        call_id = f"CALL-{uuid.uuid4().hex[:12].upper()}"
        entry_plan = analysis.get("entry_plan") or {}
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO trade_calls (id, symbol, asset_class, recommendation, probability_percent, suggested_risk_percent, entry, sl, tp, basis, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    call_id, analysis["symbol"], asset_class, analysis["recommendation"],
                    float(analysis["probability_percent"]), float(analysis["suggested_risk_percent"]),
                    entry_plan.get("entry"), entry_plan.get("sl"), entry_plan.get("tp"),
                    entry_plan.get("basis"), utc_now_iso(),
                ),
            )
        return call_id

    def recent_trade_calls(self, limit: int = 50, symbol: Optional[str] = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            if symbol:
                rows = self._conn.execute(
                    "SELECT * FROM trade_calls WHERE symbol = ? ORDER BY created_at DESC LIMIT ?", (symbol.upper(), limit)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM trade_calls ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def recent_alerts(self, limit: int = 50, symbol: Optional[str] = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            if symbol:
                rows = self._conn.execute(
                    "SELECT * FROM alerts WHERE symbol = ? ORDER BY created_at DESC LIMIT ?", (symbol.upper(), limit)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            result.append(item)
        return result

    def recent_signal_events(self, limit: int = 50, status: Optional[str] = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM signal_events WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM signal_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def risk_history(self, symbol: str, hours: int = 24) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 168)))).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT risk_score, risk_label, volatility_percent, change_percent_24h, created_at FROM risk_snapshots WHERE symbol = ? AND created_at >= ? ORDER BY created_at ASC",
                (symbol.upper(), since),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats_24h(self) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        with self._lock:
            alert_rows = self._conn.execute(
                "SELECT severity, COUNT(*) AS c FROM alerts WHERE created_at >= ? GROUP BY severity", (since,)
            ).fetchall()
            signal_rows = self._conn.execute(
                "SELECT status, COUNT(*) AS c FROM signal_events WHERE created_at >= ? GROUP BY status", (since,)
            ).fetchall()
            setups = self._conn.execute(
                "SELECT COUNT(*) AS c FROM signal_events WHERE created_at >= ? AND status = 'A_PLUS_SETUP'", (since,)
            ).fetchone()["c"]
            avg_risk_rows = self._conn.execute(
                "SELECT asset_class, AVG(risk_score) AS avg_score, MAX(risk_score) AS max_score, COUNT(*) AS c FROM risk_snapshots WHERE created_at >= ? GROUP BY asset_class",
                (since,),
            ).fetchall()
            total_scans = self._conn.execute(
                "SELECT COUNT(*) AS c FROM risk_snapshots WHERE created_at >= ?", (since,)
            ).fetchone()["c"]
            high_risk_symbols = self._conn.execute(
                """SELECT symbol, asset_class, MAX(risk_score) AS peak_score
                   FROM risk_snapshots WHERE created_at >= ? GROUP BY symbol
                   ORDER BY peak_score DESC LIMIT 5""",
                (since,),
            ).fetchall()
            trade_calls_by_recommendation = self._conn.execute(
                "SELECT recommendation, COUNT(*) AS c FROM trade_calls WHERE created_at >= ? GROUP BY recommendation",
                (since,),
            ).fetchall()

        return {
            "trade_calls_by_recommendation": {row["recommendation"]: row["c"] for row in trade_calls_by_recommendation},
            "window_hours": 24,
            "total_scans": total_scans,
            "entries_detected": setups,
            "alerts_by_severity": {row["severity"]: row["c"] for row in alert_rows},
            "signals_by_status": {row["status"]: row["c"] for row in signal_rows},
            "avg_risk_by_asset_class": {
                row["asset_class"]: {
                    "avg_score": round(float(row["avg_score"] or 0), 1),
                    "max_score": int(row["max_score"] or 0),
                    "samples": int(row["c"]),
                }
                for row in avg_risk_rows
            },
            "top_risk_symbols": [dict(row) for row in high_risk_symbols],
        }
