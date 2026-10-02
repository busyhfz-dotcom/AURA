import asyncio
import json
import logging
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

from alerts.alert_engine import AlertEngine
from alerts.telegram_notifier import TelegramNotifier
from config import load_settings
from engine.confluence_engine import ConfluenceEngine
from engine.risk_engine import RiskEngine
from engine.trade_analyst import TradeAnalyst
from news_calendar import EconomicCalendarService
from providers.market_data import MarketDataHub, classify_symbol
from scheduler import MarketMonitor
from storage.db import VertexStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VertexAPI")

settings = load_settings()
store = VertexStore(settings.database_path)
market_data = MarketDataHub(settings)
confluence = ConfluenceEngine()
risk_engine = RiskEngine()
calendar_service = EconomicCalendarService(
    provider=settings.economic_calendar_provider,
    api_key=settings.economic_calendar_api_key,
    embargo_before_minutes=settings.news_embargo_before_minutes,
    embargo_after_minutes=settings.news_embargo_after_minutes,
)
notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
alert_engine = AlertEngine(store, notifier)
trade_analyst = TradeAnalyst(confluence)
monitor = MarketMonitor(settings, market_data, confluence, risk_engine, calendar_service, alert_engine, trade_analyst)

app = FastAPI(
    title=f"{settings.brand_name} Market Intelligence API",
    version="1.0.0",
    description="Continuous crypto + forex market monitoring, structural analysis and risk alerting. Not investment advice.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    monitor.start(store)


def _disclaimer() -> str:
    return (
        "Structural analysis and risk scores are informational only and are not "
        "investment advice. No system can guarantee trading profit."
    )


@app.get("/api/health")
async def health_check():
    return {
        "status": "ONLINE",
        "brand": settings.brand_name,
        "version": "1.0.0",
        "uptime_seconds": round(monitor.uptime_seconds(), 1),
        "scan_count": monitor.scan_count(),
        "scan_interval_seconds": settings.scan_interval_seconds,
        "data_status": market_data.data_status(),
        "news_guard": calendar_service.status(),
        "telegram_configured": notifier.configured,
        "disclaimer": _disclaimer(),
    }


@app.get("/api/watchlist")
async def watchlist():
    return {
        "symbols": [
            {"symbol": symbol, "asset_class": classify_symbol(symbol)}
            for symbol in market_data.watchlist
        ]
    }


@app.get("/api/market/overview")
async def market_overview():
    items = monitor.all_latest()
    items.sort(key=lambda item: item["risk"]["risk_score"] if item.get("risk") else 0, reverse=True)
    return {"items": items, "timestamp": int(time.time()), "disclaimer": _disclaimer()}


@app.get("/api/market/{symbol}")
async def market_detail(symbol: str, limit: int = 200):
    symbol = symbol.upper().strip()
    record = monitor.latest(symbol)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol is not on the watchlist yet.")
    df, source, asset_class = market_data.get_candles(symbol, interval="15m", limit=limit)
    candles = [
        {
            "time": int(row.time.timestamp()),
            "open": round(float(row.open), 8),
            "high": round(float(row.high), 8),
            "low": round(float(row.low), 8),
            "close": round(float(row.close), 8),
        }
        for row in df.itertuples(index=False)
    ]
    return {**record, "candles": candles, "disclaimer": _disclaimer()}


@app.get("/api/risk/heatmap")
async def risk_heatmap():
    items = monitor.all_latest()
    heatmap = [
        {
            "symbol": item["symbol"],
            "asset_class": item["asset_class"],
            **item["risk"],
        }
        for item in items
        if item.get("risk")
    ]
    heatmap.sort(key=lambda row: row["risk_score"], reverse=True)
    return {"items": heatmap, "timestamp": int(time.time())}


@app.get("/api/analysis/overview")
async def analysis_overview():
    items = monitor.all_latest_analysis()
    items.sort(key=lambda item: item.get("probability_percent", 0), reverse=True)
    return {"items": items, "timestamp": int(time.time()), "analysis_count": monitor.analysis_count()}


@app.get("/api/analysis/{symbol}")
async def analysis_detail(symbol: str):
    symbol = symbol.upper().strip()
    record = monitor.latest_analysis(symbol)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analysis yet for this symbol — it may not be on the watchlist, or the analyst hasn't completed its first pass.",
        )
    return record


@app.get("/api/trade-calls")
async def trade_calls(limit: int = 50, symbol: str | None = None):
    return {"items": store.recent_trade_calls(limit=limit, symbol=symbol)}


@app.get("/api/alerts")
async def alerts(limit: int = 50, symbol: str | None = None):
    return {"items": store.recent_alerts(limit=limit, symbol=symbol)}


@app.get("/api/signals/history")
async def signal_history(limit: int = 50, status_filter: str | None = None):
    return {"items": store.recent_signal_events(limit=limit, status=status_filter)}


@app.get("/api/risk/history/{symbol}")
async def risk_history(symbol: str, hours: int = 24):
    return {"symbol": symbol.upper(), "items": store.risk_history(symbol, hours=hours)}


@app.get("/api/stats/24h")
async def stats_24h():
    return {**store.stats_24h(), "disclaimer": _disclaimer()}


@app.get("/api/calendar")
async def calendar(symbol: str | None = None, hours: int = 48):
    guard = calendar_service.status(symbol)
    return {
        **guard,
        "events": calendar_service.upcoming(hours=hours, symbol=symbol) if guard["configured"] else [],
    }


@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client connected to Vertex live feed.")
    try:
        while True:
            items = monitor.all_latest()
            items.sort(key=lambda item: item["risk"]["risk_score"] if item.get("risk") else 0, reverse=True)
            payload = {
                "timestamp": int(time.time()),
                "scan_count": monitor.scan_count(),
                "items": items,
                "disclaimer": _disclaimer(),
            }
            await websocket.send_text(json.dumps(payload, default=str))
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        logger.info("Client disconnected from Vertex live feed.")
    except Exception as exc:
        logger.exception("Live feed stream failure: %s", exc)
        await websocket.close(code=1011)
