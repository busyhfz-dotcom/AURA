import asyncio
import json
import logging
import time
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import load_settings
from engine.broker_engine import MT5ExecutionEngine
from engine.institutional_confluence import InstitutionalConfluenceEngine
from engine.market_filter import MarketFilter
from ledger import AuraLedger
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

app = FastAPI(
    title="AURA Market Intelligence API",
    version="3.2.0",
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


def capabilities() -> dict:
    news_guard = MarketFilter.news_guard_status()
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
        metadata={"version": "3.2.0", "execution_mode": settings.execution_mode},
    )


@app.get("/api/health")
async def health_check():
    news_guard = MarketFilter.news_guard_status()
    return {
        "status": "ONLINE",
        "engine_version": "3.2.0",
        "execution_mode": settings.execution_mode.upper(),
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


@app.get("/api/portfolio")
async def portfolio():
    return portfolio_payload()


@app.get("/api/audit")
async def audit(limit: int = 30):
    return {"events": ledger.recent_audit(limit)}


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

    if MarketFilter.is_news_embargo_active():
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Economic news guard is active. Execution is temporarily blocked.",
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
                "engine_version": "3.2.0",
                "market_data_source": source,
                "execution_mode": settings.execution_mode.upper(),
                "broker": broker_payload(),
                "capabilities": capabilities(),
                "active_session": MarketFilter.get_current_session(),
                "news_guard": MarketFilter.news_guard_status(),
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
