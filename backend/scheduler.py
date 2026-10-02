"""24/7 background market monitor.

Runs independently of any connected dashboard: as long as the backend
process is alive, every watched symbol is scanned on a fixed interval,
risk is scored, alerts are raised on meaningful transitions, and the
latest state is cached in memory for instant REST/WebSocket reads.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from alerts.alert_engine import AlertEngine
from config import Settings
from engine.confluence_engine import ConfluenceEngine
from engine.risk_engine import RiskEngine
from engine.trade_analyst import TREND_TIMEFRAMES, TradeAnalyst
from news_calendar import EconomicCalendarService
from providers.forex_provider import ForexProvider
from providers.market_data import MarketDataHub

logger = logging.getLogger("VertexScheduler")


class MarketMonitor:
    def __init__(
        self,
        settings: Settings,
        market_data: MarketDataHub,
        confluence: ConfluenceEngine,
        risk_engine: RiskEngine,
        calendar_service: EconomicCalendarService,
        alert_engine: AlertEngine,
        trade_analyst: TradeAnalyst,
    ):
        self.settings = settings
        self.market_data = market_data
        self.confluence = confluence
        self.risk_engine = risk_engine
        self.calendar_service = calendar_service
        self.alert_engine = alert_engine
        self.trade_analyst = trade_analyst

        self._lock = threading.RLock()
        self._state: dict[str, dict[str, Any]] = {}
        self._analysis: dict[str, dict[str, Any]] = {}
        self._scan_count = 0
        self._analysis_count = 0
        self._started_at = time.time()
        self._scan_task: asyncio.Task | None = None
        self._analysis_task: asyncio.Task | None = None

    def latest(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._state.get(symbol.upper())
            return dict(item) if item else None

    def all_latest(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._state.values()]

    def latest_analysis(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._analysis.get(symbol.upper())
            return dict(item) if item else None

    def all_latest_analysis(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._analysis.values()]

    def uptime_seconds(self) -> float:
        return time.time() - self._started_at

    def scan_count(self) -> int:
        return self._scan_count

    def analysis_count(self) -> int:
        return self._analysis_count

    def _scan_symbol(self, symbol: str) -> dict[str, Any] | None:
        try:
            # limit=220 matches _analyze_symbol's 15m request below so the two
            # loops share one forex-provider cache entry instead of each
            # paying for their own Twelve Data call on every cycle (see the
            # rate-limit note in providers/forex_provider.py).
            df, source, asset_class = self.market_data.get_candles(symbol, interval="15m", limit=220)
            # For crypto, Binance's 24h ticker is its own cheap public call, so
            # keep using it. For forex/metals, derive the snapshot from the
            # candles we just fetched instead of also calling Twelve Data's
            # /quote endpoint — that was doubling our request volume against
            # an 8-req/min free-tier quota for a value we can compute locally.
            if asset_class == "CRYPTO":
                snapshot = self.market_data.get_snapshot(symbol)
            else:
                snapshot = ForexProvider.snapshot_from_candles(symbol, df)
            signal = self.confluence.find_setup(df, symbol)
            killzone = signal.get("checklist", {}).get("killzone_active", False)
            news_status = self.calendar_service.status(symbol)
            change_percent_24h = snapshot.get("price_change_percent") if snapshot else None

            risk = self.risk_engine.score(
                symbol=symbol,
                asset_class=asset_class,
                df=df,
                killzone_active=bool(killzone),
                news_active=bool(news_status.get("active")),
                change_percent_24h=change_percent_24h,
            )

            data_available = not df.empty
            fired_alerts: list[dict[str, Any]] = []
            if data_available:
                fired_alerts = self.alert_engine.evaluate(symbol, asset_class, risk, signal)

            record = {
                "symbol": symbol,
                "asset_class": asset_class,
                "source": source,
                "data_available": data_available,
                "snapshot": snapshot,
                "signal": signal,
                "risk": risk,
                "news_guard": news_status,
                "updated_at": time.time(),
                "fired_alerts": fired_alerts,
            }
            with self._lock:
                self._state[symbol] = record
            return record
        except Exception as exc:
            logger.exception("Scan failed for %s: %s", symbol, exc)
            return None

    async def _run_loop(self, store) -> None:
        interval = self.settings.scan_interval_seconds
        logger.info("Vertex market monitor starting; watching %d symbols every %ss", len(self.market_data.watchlist), interval)
        while True:
            for symbol in self.market_data.watchlist:
                record = await asyncio.to_thread(self._scan_symbol, symbol)
                if record and record["data_available"]:
                    store.add_risk_snapshot(record["risk"])
            self._scan_count += 1
            await asyncio.sleep(interval)

    def _analyze_symbol(self, symbol: str) -> dict[str, Any] | None:
        try:
            frames: dict[str, Any] = {}
            asset_class = None
            for timeframe in TREND_TIMEFRAMES:
                df, _source, asset_class = self.market_data.get_candles(symbol, interval=timeframe, limit=220)
                frames[timeframe] = df

            existing = self.latest(symbol)
            risk = existing["risk"] if existing else self.risk_engine.score(symbol, asset_class or "UNKNOWN", frames.get("15m"), False, False)
            news_status = self.calendar_service.status(symbol)

            analysis = self.trade_analyst.analyze(symbol, frames, risk, news_status)
            analysis["asset_class"] = asset_class
            analysis["updated_at"] = time.time()

            with self._lock:
                self._analysis[symbol] = analysis

            fired_call = self.alert_engine.evaluate_trade_call(symbol, asset_class or "UNKNOWN", analysis)
            if fired_call:
                analysis["fired_alert"] = fired_call
            return analysis
        except Exception as exc:
            logger.exception("Trade analysis failed for %s: %s", symbol, exc)
            return None

    async def _run_analysis_loop(self) -> None:
        interval = self.settings.analysis_interval_seconds
        logger.info("Vertex trade analyst starting; deep-analyzing %d symbols every %ss", len(self.market_data.watchlist), interval)
        while True:
            for symbol in self.market_data.watchlist:
                await asyncio.to_thread(self._analyze_symbol, symbol)
            self._analysis_count += 1
            await asyncio.sleep(interval)

    def start(self, store) -> None:
        loop = asyncio.get_event_loop()
        if self._scan_task is None:
            self._scan_task = loop.create_task(self._run_loop(store))
        if self._analysis_task is None:
            self._analysis_task = loop.create_task(self._run_analysis_loop())

    def stop(self) -> None:
        for task in (self._scan_task, self._analysis_task):
            if task is not None:
                task.cancel()
        self._scan_task = None
        self._analysis_task = None
