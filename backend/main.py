import asyncio
import json
import logging
import time
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backtest import AuraBacktestEngine, BacktestConfig
from config import load_settings
from engine.broker_engine import MT5ExecutionEngine
from engine.institutional_confluence import InstitutionalConfluenceEngine
from engine.market_filter import MarketFilter
from ledger import AuraLedger
from news_calendar import EconomicCalendarService
from risk_guard import RiskGuard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuraTerminalAPI")

settings = load_settings()
engine = InstitutionalConfluenceEngine()
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
backtest_engine = AuraBacktestEngine(engine)

app = FastAPI(
    title="AURA Market Intelligence API",
    version="3.5.0",
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


class BacktestRequest(BaseModel):
    symbol: str = Field(default="EURUSD", min_length=3, max_length=16)
    timeframe: Literal["M5", "M15", "M30", "H1", "H4"] = "M15"
    bars: int = Field(default=1500, ge=120, le=5000)
    starting_balance: float = Field(default=10_000.0, ge=100.0, le=100_000_000.0)
    risk_percent: float = Field(default=1.0, ge=0.1, le=2.0)
    entry_wait_bars: int = Field(default=8, ge=1, le=50)
    max_hold_bars: int = Field(default=24, ge=1, le=250)


def capabilities() -> dict:
    news_guard = calendar_service.status(settings.default_symbol)
    live_ready = settings.live_execution_enabled and broker.connected and bool(settings.execution_api_key)
    return {
        "paper_execution": settings.execution_mode == "paper",
        "live_execution": live_ready,
        "auto_execution": False,
        "news_guard": news_guard["configured"],
        "position_ledger": True,
        "risk_guard": True,
    }


def broker_payload() -> dict:
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
        metadata={"version": "3.5.0", "execution_mode": settings.execution_mode},
    )


@app.get("/api/health")
async def health_check():
    news_guard = calendar_service.status(settings.default_symbol)
    return {
        "status": "ONLINE",
        "engine_version": "3.5.0",
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


@app.post("/api/backtest")
async def backtest(request: BacktestRequest):
    symbol = request.symbol.upper().strip()
    effective_risk = min(float(request.risk_percent), settings.max_risk_percent)
    try:
        candles, source = broker.get_historical_candles(symbol, timeframe=request.timeframe, n_bars=request.bars)
        result = backtest_engine.run(
            candles,
            BacktestConfig(
                symbol=symbol,
                timeframe=request.timeframe,
                starting_balance=request.starting_balance,
                risk_percent=effective_risk,
                entry_wait_bars=request.entry_wait_bars,
                max_hold_bars=request.max_hold_bars,
            ),
            source=source,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


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
    blockers.append("AUTOPILOT_WORKER_NOT_DEPLOYED")
    return {
        "enabled": False,
        "ready": False,
        "blockers": blockers,
        "broker": broker_payload(),
        "news_guard": news_guard,
        "risk_guard": risk_guard.status(),
    }


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

    if settings.live_execution_enabled and not broker.connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=broker.connection_reason or "Live broker is not connected.",
        )

    if settings.live_execution_enabled:
        try:
            live_positions = broker.live_positions()
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        if len(live_positions) >= settings.max_open_positions:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail={"code": "MAX_OPEN_POSITIONS", "message": "Live broker position limit reached."},
            )
        if any(position["symbol"].upper() == symbol for position in live_positions):
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail={"code": "DUPLICATE_SYMBOL", "message": f"MT5 already has an open {symbol} position."},
            )

    try:
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
        return {**result, **refs, "risk_guard": risk_guard.status()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        ledger.add_audit("execution.error", str(exc), severity="error", metadata={"symbol": symbol})
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
                "engine_version": "3.5.0",
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
