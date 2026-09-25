import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import pandas as pd

from backtesting import BacktestConfig, HistoricalBacktestEngine
from config import load_settings
from engine.broker_engine import MT5ExecutionEngine
from engine.institutional_confluence import InstitutionalConfluenceEngine
from engine.market_filter import MarketFilter
from execution_client import ExecutionWorkerClient
from ledger import AuraLedger
from news_calendar import EconomicCalendarService
from risk_guard import RiskGuard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuraTerminalAPI")

settings = load_settings()
engine = InstitutionalConfluenceEngine()
backtester = HistoricalBacktestEngine(engine)
broker = MT5ExecutionEngine(settings)
ledger = AuraLedger(settings.database_path, settings.paper_starting_balance)
risk_guard = RiskGuard(
    ledger=ledger,
    max_open_positions=settings.max_open_positions,
    max_trades_per_day=settings.max_trades_per_day,
    max_daily_loss_percent=settings.max_daily_loss_percent,
)
calendar_service = EconomicCalendarService(
    provider=settings.economic_calendar_provider,
    api_key=settings.economic_calendar_api_key,
    embargo_before_minutes=settings.news_embargo_before_minutes,
    embargo_after_minutes=settings.news_embargo_after_minutes,
)
execution_worker = ExecutionWorkerClient(
    base_url=settings.execution_worker_url,
    shared_secret=settings.execution_worker_secret,
    timeout_seconds=settings.execution_worker_timeout_seconds,
)
_worker_health_cache: dict = {"at": 0.0, "payload": None}

app = FastAPI(
    title="AURA Market Intelligence API",
    version="3.7.0",
    description="Market structure analytics, durable execution audit and guarded trading infrastructure for AURA Terminal.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ExecutionRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=16)
    action: Literal["BUY", "SELL"]
    entry: float = Field(gt=0)
    sl: float = Field(gt=0)
    tp: float = Field(gt=0)
    risk_percent: float = Field(default=0.5, ge=0.1, le=2.0)


class SizingRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=16)
    action: Literal["BUY", "SELL"]
    entry: float = Field(gt=0)
    sl: float = Field(gt=0)
    risk_percent: float = Field(default=0.5, ge=0.1, le=2.0)


class LiveCloseRequest(BaseModel):
    ticket: int = Field(gt=0)
    volume: float | None = Field(default=None, gt=0)


class LiveModifyRequest(BaseModel):
    ticket: int = Field(gt=0)
    sl: float | None = Field(default=None, gt=0)
    tp: float | None = Field(default=None, gt=0)


class HistoricalBar(BaseModel):
    time: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)


class BacktestRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=16)
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1"] = "M15"
    source: Literal["UPLOAD", "MT5"] = "UPLOAD"
    bars: list[HistoricalBar] = Field(default_factory=list, max_length=50_000)
    start: datetime | None = None
    end: datetime | None = None
    initial_balance: float = Field(default=10_000.0, gt=0, le=100_000_000)
    risk_percent: float = Field(default=0.5, ge=0.1, le=2.0)
    max_hold_bars: int = Field(default=96, ge=1, le=500)


def _worker_health(force: bool = False) -> dict:
    if not execution_worker.configured:
        return {
            "status": "NOT_CONFIGURED",
            "connected": False,
            "provider": "MT5 Execution Worker",
            "reason": "AURA_EXECUTION_WORKER_URL and AURA_EXECUTION_WORKER_SECRET are required.",
        }
    now = time.time()
    cached = _worker_health_cache.get("payload")
    if not force and cached and now - float(_worker_health_cache.get("at") or 0) < 5:
        return cached
    try:
        payload = execution_worker.health()
    except RuntimeError as exc:
        payload = {
            "status": "UNAVAILABLE",
            "connected": False,
            "provider": "MT5 Execution Worker",
            "reason": str(exc),
        }
    _worker_health_cache["at"] = now
    _worker_health_cache["payload"] = payload
    return payload


def _live_transport_health() -> dict:
    if settings.live_execution_transport == "worker":
        return _worker_health()
    state = broker.state
    return {
        "status": "ONLINE" if state.connected else "UNAVAILABLE",
        "connected": state.connected,
        "provider": state.provider,
        "reason": state.reason,
        "transport": "direct_mt5",
    }


def _live_positions() -> list[dict]:
    if settings.live_execution_transport == "worker":
        if not execution_worker.configured:
            raise RuntimeError("Isolated execution worker is not configured.")
        return execution_worker.positions()
    if settings.live_execution_transport == "direct_mt5":
        return broker.live_positions()
    raise RuntimeError(f"Unsupported live execution transport: {settings.live_execution_transport}")


def capabilities() -> dict:
    news_guard = calendar_service.status(settings.default_symbol)
    transport = _live_transport_health()
    live_ready = (
        settings.live_execution_enabled
        and bool(transport.get("connected"))
        and bool(settings.execution_api_key)
        and bool(news_guard.get("configured"))
        and bool(news_guard.get("safe"))
    )
    return {
        "paper_execution": settings.execution_mode == "paper",
        "live_execution": live_ready,
        "auto_execution": False,
        "news_guard": news_guard["configured"],
        "position_ledger": True,
        "risk_guard": True,
        "idempotent_execution": True,
        "execution_transport": settings.live_execution_transport,
        "isolated_worker": settings.live_execution_transport == "worker",
    }


def broker_payload() -> dict:
    if settings.execution_mode == "live":
        return _live_transport_health()
    state = broker.state
    return {
        "connected": state.connected,
        "provider": state.provider,
        "reason": state.reason,
    }


def _mark_for_symbol(symbol: str) -> float | None:
    try:
        df, _ = broker.get_market_candles(symbol, n_bars=2)
        if df.empty:
            return None
        return float(df.iloc[-1]["close"])
    except Exception:
        logger.exception("Unable to mark %s", symbol)
        return None


def portfolio_payload() -> dict:
    positions = ledger.open_positions()
    enriched = []
    marks: dict[str, float | None] = {}
    unrealized = 0.0
    for position in positions:
        symbol = position["symbol"]
        if symbol not in marks:
            marks[symbol] = _mark_for_symbol(symbol)
        mark = marks[symbol]
        pnl = ledger.estimate_pnl(position, mark) if mark is not None and position["status"] == "OPEN" else 0.0
        unrealized += pnl
        enriched.append({**position, "mark_price": mark, "unrealized_pnl": pnl})

    metrics = ledger.metrics()
    equity = metrics["balance"] + unrealized
    return {
        "account": {
            **metrics,
            "unrealized_pnl": round(unrealized, 2),
            "equity": round(equity, 2),
        },
        "positions": enriched,
        "recent_orders": ledger.recent_orders(10),
        "risk_guard": risk_guard.status(),
    }


@app.on_event("startup")
async def startup_event():
    ledger.add_audit(
        "system.start",
        "AURA API started.",
        metadata={"version": "3.7.0", "execution_mode": settings.execution_mode},
    )


@app.get("/api/health")
async def health_check():
    news_guard = calendar_service.status(settings.default_symbol)
    return {
        "status": "ONLINE",
        "engine_version": "3.7.0",
        "execution_mode": settings.execution_mode.upper(),
        "max_risk_percent": settings.max_risk_percent,
        "broker": broker_payload(),
        "capabilities": capabilities(),
        "active_session": MarketFilter.get_current_session(),
        "news_guard": news_guard,
        "risk_guard": risk_guard.status(),
    }


@app.get("/api/market/{symbol}")
async def market_snapshot(symbol: str):
    symbol = symbol.upper().strip()
    df, source = broker.get_market_candles(symbol)
    analysis = engine.find_high_probability_setup(df, symbol)
    return {
        "timestamp": int(time.time()),
        "market_data_source": source,
        "market_status": broker.market_status(symbol, df=df, source=source),
        "signal": analysis,
        "candles": [
            {
                "time": int(row.time.timestamp()),
                "open": round(float(row.open), 6),
                "high": round(float(row.high), 6),
                "low": round(float(row.low), 6),
                "close": round(float(row.close), 6),
            }
            for row in df.itertuples(index=False)
        ],
    }


WATCHLIST_SYMBOLS = ("EURUSD", "XAUUSD", "GBPUSD", "USDJPY", "BTCUSD", "ETHUSD", "NAS100", "USOIL", "SP500")


@app.get("/api/markets")
async def market_board():
    items = []
    for symbol in WATCHLIST_SYMBOLS:
        try:
            df, source = broker.get_market_candles(symbol, n_bars=48)
            if df.empty:
                continue
            current = float(df.iloc[-1]["close"])
            previous = float(df.iloc[-2]["close"]) if len(df) > 1 else current
            day_open = float(df.iloc[0]["open"])
            change = current - previous
            change_percent = ((current - day_open) / day_open * 100.0) if day_open else 0.0
            items.append({
                "symbol": symbol,
                "price": round(current, 6),
                "change": round(change, 6),
                "change_percent": round(change_percent, 3),
                "source": source,
                "sparkline": [round(float(value), 6) for value in df.tail(24)["close"].tolist()],
            })
        except Exception as exc:
            logger.warning("Unable to build market board row for %s: %s", symbol, exc)
    return {"items": items, "timestamp": int(time.time())}


@app.get("/api/signals")
async def signal_board():
    items = []
    for symbol in WATCHLIST_SYMBOLS:
        try:
            df, source = broker.get_market_candles(symbol)
            analysis = engine.find_high_probability_setup(df, symbol)
            items.append({
                "symbol": symbol,
                "source": source,
                "market_status": broker.market_status(symbol, df=df, source=source),
                "signal": analysis,
            })
        except Exception as exc:
            logger.warning("Unable to build signal board row for %s: %s", symbol, exc)
    return {"items": items, "timestamp": int(time.time())}


@app.get("/api/orders")
async def orders(limit: int = 50):
    return {"orders": ledger.recent_orders(limit)}


@app.get("/api/positions")
async def positions(closed_limit: int = 100):
    payload = portfolio_payload()
    return {
        "open": payload["positions"],
        "closed": ledger.closed_positions(closed_limit),
        "account": payload["account"],
    }


@app.get("/api/performance")
async def performance():
    return {
        **ledger.performance_summary(),
        "account": ledger.metrics(),
    }


@app.get("/api/analytics")
async def analytics():
    return {
        "performance": ledger.performance_summary(),
        "risk_guard": risk_guard.status(),
        "account": portfolio_payload()["account"],
        "recent_audit": ledger.recent_audit(12),
    }


@app.get("/api/calendar")
async def calendar(symbol: str | None = None, hours: int = 48):
    guard = calendar_service.status(symbol)
    return {
        "configured": guard["configured"],
        "provider": guard.get("provider"),
        "provider_error": guard.get("provider_error"),
        "guard_active": guard["active"],
        "safe": guard.get("safe", False),
        "message": guard.get("message"),
        "embargo_before_minutes": guard.get("embargo_before_minutes"),
        "embargo_after_minutes": guard.get("embargo_after_minutes"),
        "blocking_events": guard.get("blocking_events", []),
        "events": calendar_service.upcoming(hours=hours, symbol=symbol) if guard["configured"] else [],
    }


@app.get("/api/auto-trade")
async def auto_trade_status():
    news_guard = calendar_service.status(settings.default_symbol)
    blockers = []
    if settings.execution_mode != "live":
        blockers.append("LIVE_MODE_REQUIRED")
    if not broker.connected:
        blockers.append("BROKER_NOT_CONNECTED")
    if not settings.execution_api_key:
        blockers.append("EXECUTION_KEY_REQUIRED")
    if not news_guard["configured"]:
        blockers.append("NEWS_GUARD_REQUIRED")
    elif news_guard.get("provider_error"):
        blockers.append("NEWS_GUARD_UNHEALTHY")
    elif news_guard.get("active"):
        blockers.append("NEWS_EMBARGO_ACTIVE")
    elif not news_guard.get("safe"):
        blockers.append("NEWS_GUARD_UNHEALTHY")
    blockers.append("AUTOPILOT_WORKER_NOT_DEPLOYED")
    return {
        "enabled": False,
        "ready": False,
        "blockers": blockers,
        "broker": broker_payload(),
        "news_guard": news_guard,
        "risk_guard": risk_guard.status(),
    }


@app.get("/api/backtests/capabilities")
async def backtest_capabilities():
    return {
        "upload_ohlc": True,
        "mt5_history": bool(broker.connected),
        "simulation_history": False,
        "max_risk_percent": settings.max_risk_percent,
        "supported_timeframes": ["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
        "message": (
            "Use verified MT5 history or uploaded OHLC data. AURA simulation data is never used for performance backtests."
        ),
    }


@app.get("/api/backtests")
async def backtests(limit: int = 20):
    return {"runs": ledger.recent_backtests(limit)}


@app.get("/api/backtests/{run_id}")
async def backtest_detail(run_id: str):
    result = ledger.backtest_run(run_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found.")
    return result


@app.post("/api/backtests/run")
async def run_backtest(request: BacktestRequest):
    symbol = request.symbol.upper().strip()
    try:
        if request.source == "MT5":
            if request.start is None or request.end is None:
                raise ValueError("MT5 backtests require start and end timestamps.")
            history, source = broker.get_historical_candles(
                symbol=symbol,
                timeframe=request.timeframe,
                start=request.start,
                end=request.end,
            )
        else:
            if len(request.bars) < 80:
                raise ValueError("Upload at least 80 valid OHLC candles.")
            history = pd.DataFrame([bar.model_dump() for bar in request.bars])
            source = "USER_OHLC"

        result = backtester.run(
            history,
            BacktestConfig(
                symbol=symbol,
                timeframe=request.timeframe,
                initial_balance=request.initial_balance,
                risk_percent=min(request.risk_percent, settings.max_risk_percent),
                max_hold_bars=request.max_hold_bars,
            ),
            source=source,
        )
        run_id = ledger.record_backtest(result)
        return {**result, "id": run_id}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/api/portfolio")
async def portfolio():
    return portfolio_payload()


@app.get("/api/audit")
async def audit(limit: int = 30):
    return {"events": ledger.recent_audit(limit)}


@app.post("/api/risk/preview")
async def risk_preview(request: SizingRequest):
    symbol = request.symbol.upper().strip()
    try:
        preview = broker.preview_position_size(
            symbol=symbol,
            action=request.action,
            entry=request.entry,
            sl=request.sl,
            risk_percent=request.risk_percent,
            balance=ledger.metrics()["balance"],
        )
        return {**preview, "risk_guard": risk_guard.status()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/trade/execute")
async def execute_trade(
    trade: ExecutionRequest,
    x_aura_execution_key: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    symbol = trade.symbol.upper().strip()

    if settings.live_execution_enabled:
        if not settings.execution_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Live execution is locked until AURA_EXECUTION_API_KEY is configured.",
            )
        if x_aura_execution_key != settings.execution_api_key:
            ledger.add_audit(
                "security.execution_denied",
                "Live execution denied because the operator key was missing or invalid.",
                severity="warning",
                metadata={"symbol": symbol},
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator execution key.")
        if not idempotency_key:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail="Live execution requires an Idempotency-Key header.",
            )

    news_guard = calendar_service.status(symbol)
    if settings.live_execution_enabled and not news_guard.get("configured"):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Live execution is blocked until a verified economic calendar provider is configured.",
        )
    if settings.live_execution_enabled and not news_guard.get("safe", False):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=news_guard.get("message") or "Economic News Guard cannot verify a safe execution window.",
        )
    if news_guard.get("active"):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="High-impact economic news embargo is active. Execution is temporarily blocked.",
        )

    decision = risk_guard.evaluate(symbol)
    if not decision.allowed:
        ledger.add_audit(
            "execution.blocked",
            decision.message,
            severity="warning",
            metadata={"code": decision.code, "symbol": symbol},
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={"code": decision.code, "message": decision.message},
        )

    request_payload = {
        "symbol": symbol,
        "action": trade.action,
        "entry": trade.entry,
        "sl": trade.sl,
        "tp": trade.tp,
        "risk_percent": trade.risk_percent,
        "mode": settings.execution_mode,
        "transport": settings.live_execution_transport if settings.live_execution_enabled else "paper",
    }
    request_hash = hashlib.sha256(
        json.dumps(request_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    reservation = None
    if idempotency_key:
        try:
            reservation = ledger.reserve_execution_request(idempotency_key, request_hash)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        if reservation["state"] == "COMPLETED" and reservation.get("result"):
            return {**reservation["result"], "idempotent_replay": True}
        if reservation["state"] == "FAILED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=reservation.get("error_message") or "This execution key is bound to a failed request. Use a new key after review.",
            )
        if not reservation.get("is_new") and settings.live_execution_transport != "worker":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Execution is already pending or unknown. Direct MT5 requests are not retried automatically.",
            )

    if settings.live_execution_enabled:
        transport = _live_transport_health()
        if not transport.get("connected"):
            detail = transport.get("reason") or "Live execution transport is unavailable."
            if idempotency_key:
                ledger.fail_execution_request(idempotency_key, detail)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)

        try:
            live_positions = _live_positions()
        except RuntimeError as exc:
            if idempotency_key:
                ledger.fail_execution_request(idempotency_key, str(exc))
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if len(live_positions) >= settings.max_open_positions:
            if idempotency_key:
                ledger.fail_execution_request(idempotency_key, "Live broker position limit reached.")
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail={"code": "MAX_OPEN_POSITIONS", "message": "Live broker position limit reached."},
            )
        if any(str(position.get("symbol", "")).upper() == symbol for position in live_positions):
            if idempotency_key:
                ledger.fail_execution_request(idempotency_key, f"Open {symbol} position already exists.")
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail={"code": "DUPLICATE_SYMBOL", "message": f"Live broker already has an open {symbol} position."},
            )

    try:
        if settings.live_execution_enabled and settings.live_execution_transport == "worker":
            if not idempotency_key:
                raise RuntimeError("Worker execution requires an idempotency key.")
            result = execution_worker.execute({
                "idempotency_key": idempotency_key,
                "symbol": symbol,
                "action": trade.action,
                "entry": trade.entry,
                "sl": trade.sl,
                "tp": trade.tp,
                "risk_percent": min(trade.risk_percent, settings.max_risk_percent),
            })
        else:
            result = broker.send_order(
                symbol=symbol,
                action=trade.action,
                entry=trade.entry,
                sl=trade.sl,
                tp=trade.tp,
                risk_percent=trade.risk_percent,
                paper_balance=ledger.metrics()["balance"] if settings.execution_mode == "paper" else None,
            )

        refs = ledger.record_execution(result)
        response_payload = {**result, **refs, "risk_guard": risk_guard.status()}
        if idempotency_key:
            ledger.complete_execution_request(idempotency_key, response_payload)
        return response_payload
    except ValueError as exc:
        if idempotency_key:
            ledger.fail_execution_request(idempotency_key, str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        if idempotency_key:
            if settings.live_execution_enabled:
                ledger.mark_execution_request_unknown(idempotency_key, str(exc))
            else:
                ledger.fail_execution_request(idempotency_key, str(exc))
        ledger.add_audit(
            "execution.error",
            str(exc),
            severity="error",
            metadata={"symbol": symbol, "idempotency_key": idempotency_key, "transport": settings.live_execution_transport},
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/api/live/positions")
async def live_positions(x_aura_execution_key: str | None = Header(default=None)):
    if not settings.live_execution_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AURA is not in live execution mode.")
    if x_aura_execution_key != settings.execution_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator execution key.")
    try:
        return {"transport": settings.live_execution_transport, "positions": _live_positions()}
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/live/positions/close")
async def close_live_position(
    request: LiveCloseRequest,
    x_aura_execution_key: str | None = Header(default=None),
):
    if not settings.live_execution_enabled or settings.live_execution_transport != "worker":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Live close requires isolated worker transport.")
    if x_aura_execution_key != settings.execution_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator execution key.")
    try:
        result = execution_worker.close_position(request.ticket, request.volume)
        ledger.add_audit("live.position_closed", f"Live MT5 position {request.ticket} close confirmed.", metadata=result)
        return result
    except RuntimeError as exc:
        ledger.add_audit("live.close_error", str(exc), severity="error", metadata={"ticket": request.ticket})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/live/positions/modify")
async def modify_live_position(
    request: LiveModifyRequest,
    x_aura_execution_key: str | None = Header(default=None),
):
    if not settings.live_execution_enabled or settings.live_execution_transport != "worker":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Live modify requires isolated worker transport.")
    if x_aura_execution_key != settings.execution_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator execution key.")
    try:
        result = execution_worker.modify_position(request.ticket, request.sl, request.tp)
        ledger.add_audit("live.position_modified", f"Live MT5 position {request.ticket} protection updated.", metadata=result)
        return result
    except RuntimeError as exc:
        ledger.add_audit("live.modify_error", str(exc), severity="error", metadata={"ticket": request.ticket})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/positions/{position_id}/close")
async def close_paper_position(position_id: str):
    positions = {position["id"]: position for position in ledger.open_positions()}
    position = positions.get(position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Open position not found.")
    if settings.execution_mode != "paper":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Paper position closing endpoint is disabled while AURA is in live mode.",
        )

    mark = _mark_for_symbol(position["symbol"])
    if mark is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Market price unavailable.")
    try:
        return {**ledger.close_position(position_id, mark), "portfolio": portfolio_payload()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket):
    await websocket.accept()
    symbol = (websocket.query_params.get("symbol") or settings.default_symbol).upper().strip()
    logger.info("Client connected to AURA analytics stream for %s.", symbol)
    try:
        while True:
            df, source = broker.get_market_candles(symbol)
            analysis = engine.find_high_probability_setup(df, symbol)
            payload = {
                "timestamp": int(time.time()),
                "engine_version": "3.7.0",
                "market_data_source": source,
                "market_status": broker.market_status(symbol, df=df, source=source),
                "execution_mode": settings.execution_mode.upper(),
                "max_risk_percent": settings.max_risk_percent,
                "broker": broker_payload(),
                "capabilities": capabilities(),
                "active_session": MarketFilter.get_current_session(),
                "news_guard": calendar_service.status(symbol),
                "risk_guard": risk_guard.status(),
                "portfolio": portfolio_payload(),
                "signal": analysis,
                "candles": [
                    {
                        "time": int(row.time.timestamp()),
                        "open": round(float(row.open), 6),
                        "high": round(float(row.high), 6),
                        "low": round(float(row.low), 6),
                        "close": round(float(row.close), 6),
                    }
                    for row in df.tail(160).itertuples(index=False)
                ],
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        logger.info("Client disconnected from AURA analytics stream.")
    except Exception as exc:
        logger.exception("Signal stream failure: %s", exc)
        await websocket.close(code=1011)
