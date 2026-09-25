from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AuraExecutionWorker")


def optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


SHARED_SECRET = os.getenv("AURA_WORKER_SHARED_SECRET", "")
DATABASE = os.getenv("AURA_WORKER_DATABASE", "./data/execution-worker.db")
SIGNATURE_TOLERANCE = max(5, min(int(os.getenv("AURA_WORKER_SIGNATURE_TOLERANCE_SECONDS", "30")), 300))
DEVIATION = max(1, min(int(os.getenv("AURA_MT5_DEVIATION", "20")), 100))
MAX_RISK = max(0.1, min(float(os.getenv("AURA_MAX_RISK_PERCENT", "1.0")), 2.0))
MT5_ACCOUNT = optional_int(os.getenv("MT5_ACCOUNT"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD") or None
MT5_SERVER = os.getenv("MT5_SERVER") or None


class CandlesRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=16)
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1"] = "M15"
    bars: int = Field(default=200, ge=40, le=5000)


class ExecuteRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    symbol: str = Field(min_length=3, max_length=16)
    action: Literal["BUY", "SELL"]
    entry: float = Field(gt=0)
    sl: float = Field(gt=0)
    tp: float = Field(gt=0)
    risk_percent: float = Field(ge=0.1, le=2.0)


class CloseRequest(BaseModel):
    ticket: int = Field(gt=0)
    volume: float | None = Field(default=None, gt=0)


class ModifyRequest(BaseModel):
    ticket: int = Field(gt=0)
    sl: float | None = Field(default=None, gt=0)
    tp: float | None = Field(default=None, gt=0)


class WorkerStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS execution_requests (
                    idempotency_key TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_worker_exec_updated
                ON execution_requests(updated_at DESC);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def reserve(self, key: str, request_hash: str) -> dict:
        now = self._now()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM execution_requests WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                item = dict(row)
                if item["request_hash"] != request_hash:
                    raise ValueError("Idempotency key is already bound to another request.")
                item["result"] = json.loads(item["result_json"]) if item.get("result_json") else None
                item["is_new"] = False
                return item

            self._conn.execute(
                """
                INSERT INTO execution_requests
                (idempotency_key, request_hash, state, created_at, updated_at)
                VALUES (?, ?, 'PENDING', ?, ?)
                """,
                (key, request_hash, now, now),
            )
        return {"idempotency_key": key, "state": "PENDING", "result": None, "is_new": True}

    def complete(self, key: str, result: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE execution_requests
                SET state='COMPLETED', result_json=?, error_message=NULL, updated_at=?
                WHERE idempotency_key=?
                """,
                (json.dumps(result), self._now(), key),
            )

    def fail(self, key: str, message: str, state: str = "FAILED") -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE execution_requests
                SET state=?, error_message=?, updated_at=?
                WHERE idempotency_key=?
                """,
                (state, message, self._now(), key),
            )


class MT5Worker:
    def __init__(self):
        self.connected = False
        self.reason: str | None = None
        self._connect()

    def _connect(self) -> None:
        if not MT5_AVAILABLE:
            self.reason = "MetaTrader5 Python package is unavailable. Run the worker on Windows with MT5 installed."
            return
        if not mt5.initialize():
            self.reason = f"MT5 initialize failed: {mt5.last_error()}"
            return
        if all([MT5_ACCOUNT, MT5_PASSWORD, MT5_SERVER]):
            if not mt5.login(MT5_ACCOUNT, password=MT5_PASSWORD, server=MT5_SERVER):
                self.reason = f"MT5 login failed: {mt5.last_error()}"
                return
        account = mt5.account_info()
        if account is None:
            self.reason = "MT5 initialized but no account is available."
            return
        self.connected = True
        self.reason = None

    def health(self) -> dict:
        account = mt5.account_info() if self.connected else None
        return {
            "status": "ONLINE" if self.connected else "UNAVAILABLE",
            "connected": self.connected,
            "provider": "MetaTrader 5",
            "account": int(account.login) if account is not None else None,
            "server": getattr(account, "server", None) if account is not None else None,
            "reason": self.reason,
        }

    @staticmethod
    def _tag(key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12].upper()
        return f"AURA-{digest}"

    def _ensure(self) -> None:
        if not self.connected:
            raise RuntimeError(self.reason or "MT5 worker is not connected.")

    def candles(self, symbol: str, timeframe: str, bars: int) -> dict:
        self._ensure()
        symbol = symbol.upper().strip()
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Unable to select {symbol} in MT5.")
        timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }
        if timeframe not in timeframe_map:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        rates = mt5.copy_rates_from_pos(symbol, timeframe_map[timeframe], 0, max(40, min(int(bars), 5000)))
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No MT5 historical candles are available for {symbol} {timeframe}.")
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "MT5_WORKER",
            "candles": [{
                "time": int(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            } for row in rates],
        }

    def positions(self) -> list[dict]:
        self._ensure()
        rows = mt5.positions_get()
        if rows is None:
            raise RuntimeError(f"Unable to read MT5 positions: {mt5.last_error()}")
        return [{
            "ticket": int(row.ticket),
            "symbol": row.symbol,
            "action": "BUY" if row.type == mt5.POSITION_TYPE_BUY else "SELL",
            "volume": float(row.volume),
            "price_open": float(row.price_open),
            "price_current": float(row.price_current),
            "sl": float(row.sl),
            "tp": float(row.tp),
            "profit": float(row.profit),
            "comment": getattr(row, "comment", ""),
        } for row in rows]

    def _volume(self, symbol: str, action: str, entry: float, sl: float, risk_percent: float) -> float:
        account = mt5.account_info()
        info = mt5.symbol_info(symbol)
        if account is None or info is None:
            raise RuntimeError("Unable to read MT5 account or symbol metadata.")
        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        loss_one_lot = mt5.order_calc_profit(order_type, symbol, 1.0, entry, sl)
        if loss_one_lot is None or loss_one_lot == 0:
            raise RuntimeError("MT5 could not calculate requested stop-loss risk.")
        risk_amount = float(account.balance) * (min(risk_percent, MAX_RISK) / 100.0)
        raw = risk_amount / abs(loss_one_lot)
        step = float(info.volume_step or 0.01)
        volume = math.floor(raw / step) * step
        volume = max(float(info.volume_min), min(float(info.volume_max), volume))
        precision = max(0, int(round(-math.log10(step)))) if step < 1 else 0
        return round(volume, precision)

    def _filling_mode(self, symbol: str, request: dict) -> int:
        info = mt5.symbol_info(symbol)
        candidates: list[int] = []
        if info is not None:
            flags = int(getattr(info, "filling_mode", 0) or 0)
            pairs = [
                (getattr(mt5, "SYMBOL_FILLING_IOC", 2), mt5.ORDER_FILLING_IOC),
                (getattr(mt5, "SYMBOL_FILLING_FOK", 1), mt5.ORDER_FILLING_FOK),
            ]
            for flag, order_mode in pairs:
                if flags & int(flag):
                    candidates.append(order_mode)
        candidates.extend([mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN])
        seen = set()
        errors = []
        for mode in candidates:
            if mode in seen:
                continue
            seen.add(mode)
            check = mt5.order_check({**request, "type_filling": mode})
            if check is not None and check.retcode == 0:
                return mode
            errors.append(getattr(check, "comment", str(mt5.last_error())) if check else str(mt5.last_error()))
        raise RuntimeError("No broker-supported filling mode passed MT5 order_check: " + " | ".join(errors))

    def recover(self, idempotency_key: str, request: ExecuteRequest) -> dict | None:
        self._ensure()
        tag = self._tag(idempotency_key)
        start = datetime.now(timezone.utc) - timedelta(days=7)
        end = datetime.now(timezone.utc) + timedelta(minutes=1)
        deals = mt5.history_deals_get(start, end)
        if deals is None:
            return None
        matches = [deal for deal in deals if tag in str(getattr(deal, "comment", "")) and str(deal.symbol).upper() == request.symbol.upper()]
        if not matches:
            return None
        deal = matches[-1]
        return {
            "status": "FILLED_RECOVERED",
            "mode": "live",
            "order_id": int(getattr(deal, "order", 0) or 0),
            "deal_id": int(deal.ticket),
            "symbol": request.symbol.upper(),
            "action": request.action,
            "lots": float(deal.volume),
            "entry_price": float(deal.price),
            "sl": request.sl,
            "tp": request.tp,
            "risk_percent": min(request.risk_percent, MAX_RISK),
            "worker_idempotency_key": idempotency_key,
            "message": "Existing MT5 deal recovered from the worker idempotency tag; no new order was sent.",
        }

    def execute(self, request: ExecuteRequest) -> dict:
        self._ensure()
        symbol = request.symbol.upper().strip()
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Unable to select {symbol} in MT5.")
        if request.action == "BUY" and not (request.sl < request.entry < request.tp):
            raise ValueError("BUY requires SL < entry < TP.")
        if request.action == "SELL" and not (request.tp < request.entry < request.sl):
            raise ValueError("SELL requires TP < entry < SL.")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No current MT5 tick for {symbol}.")
        market_price = float(tick.ask if request.action == "BUY" else tick.bid)
        order_type = mt5.ORDER_TYPE_BUY if request.action == "BUY" else mt5.ORDER_TYPE_SELL
        volume = self._volume(symbol, request.action, market_price, request.sl, request.risk_percent)
        tag = self._tag(request.idempotency_key)

        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": market_price,
            "sl": request.sl,
            "tp": request.tp,
            "deviation": DEVIATION,
            "magic": 240370,
            "comment": tag,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        order["type_filling"] = self._filling_mode(symbol, order)
        check = mt5.order_check(order)
        if check is None or check.retcode != 0:
            raise RuntimeError(f"MT5 order check failed: {getattr(check, 'comment', mt5.last_error())}")
        result = mt5.order_send(order)
        if result is None:
            raise RuntimeError(f"MT5 order_send returned no result: {mt5.last_error()}")
        if result.retcode not in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL}:
            raise RuntimeError(f"MT5 rejected order ({result.retcode}): {result.comment}")

        return {
            "status": "FILLED",
            "mode": "live",
            "order_id": int(result.order),
            "deal_id": int(result.deal),
            "symbol": symbol,
            "action": request.action,
            "lots": float(volume),
            "entry_price": float(result.price or market_price),
            "sl": request.sl,
            "tp": request.tp,
            "risk_percent": min(request.risk_percent, MAX_RISK),
            "worker_idempotency_key": request.idempotency_key,
            "message": "Order confirmed by isolated MT5 execution worker.",
        }

    def close(self, ticket: int, requested_volume: float | None = None) -> dict:
        self._ensure()
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise ValueError("MT5 position was not found.")
        position = positions[0]
        symbol = position.symbol
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No current MT5 tick for {symbol}.")
        is_buy = position.type == mt5.POSITION_TYPE_BUY
        action = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price = float(tick.bid if is_buy else tick.ask)
        volume = float(requested_volume or position.volume)
        volume = min(volume, float(position.volume))
        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "position": int(position.ticket),
            "volume": volume,
            "type": action,
            "price": price,
            "deviation": DEVIATION,
            "magic": 240370,
            "comment": "AURA-CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        order["type_filling"] = self._filling_mode(symbol, order)
        result = mt5.order_send(order)
        if result is None or result.retcode not in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL}:
            detail = getattr(result, "comment", str(mt5.last_error())) if result else str(mt5.last_error())
            raise RuntimeError(f"MT5 close failed: {detail}")
        return {"status": "CLOSED", "ticket": ticket, "deal_id": int(result.deal), "volume": volume, "price": float(result.price or price)}

    def modify(self, ticket: int, sl: float | None, tp: float | None) -> dict:
        self._ensure()
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise ValueError("MT5 position was not found.")
        position = positions[0]
        new_sl = float(sl if sl is not None else position.sl)
        new_tp = float(tp if tp is not None else position.tp)
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(position.ticket),
            "symbol": position.symbol,
            "sl": new_sl,
            "tp": new_tp,
            "magic": 240370,
            "comment": "AURA-MODIFY",
        })
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            detail = getattr(result, "comment", str(mt5.last_error())) if result else str(mt5.last_error())
            raise RuntimeError(f"MT5 modify failed: {detail}")
        return {"status": "MODIFIED", "ticket": ticket, "sl": new_sl, "tp": new_tp}


store = WorkerStore(DATABASE)
broker = MT5Worker()
app = FastAPI(title="AURA MT5 Execution Worker", version="3.7.0")


async def verify_signature(
    request: Request,
    x_aura_timestamp: str | None = Header(default=None),
    x_aura_signature: str | None = Header(default=None),
) -> bytes:
    if not SHARED_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Worker shared secret is not configured.")
    if not x_aura_timestamp or not x_aura_signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing worker signature headers.")
    try:
        timestamp = int(x_aura_timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker timestamp.") from exc
    if abs(int(time.time()) - timestamp) > SIGNATURE_TOLERANCE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker request timestamp is outside the allowed window.")

    body = await request.body()
    path = request.url.path
    material = b".".join([
        str(timestamp).encode("utf-8"),
        request.method.upper().encode("utf-8"),
        path.encode("utf-8"),
        body,
    ])
    expected = hmac.new(SHARED_SECRET.encode("utf-8"), material, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_aura_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker signature.")
    return body


@app.get("/health")
async def health(request: Request, x_aura_timestamp: str | None = Header(default=None), x_aura_signature: str | None = Header(default=None)):
    await verify_signature(request, x_aura_timestamp, x_aura_signature)
    return {**broker.health(), "worker_version": "3.7.0", "idempotency_store": True}


@app.post("/market/candles")
async def market_candles(request: Request, x_aura_timestamp: str | None = Header(default=None), x_aura_signature: str | None = Header(default=None)):
    raw = await verify_signature(request, x_aura_timestamp, x_aura_signature)
    payload = CandlesRequest.model_validate_json(raw)
    try:
        return broker.candles(payload.symbol, payload.timeframe, payload.bars)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/positions")
async def positions(request: Request, x_aura_timestamp: str | None = Header(default=None), x_aura_signature: str | None = Header(default=None)):
    await verify_signature(request, x_aura_timestamp, x_aura_signature)
    try:
        return {"positions": broker.positions()}
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/execute")
async def execute(request: Request, x_aura_timestamp: str | None = Header(default=None), x_aura_signature: str | None = Header(default=None)):
    raw = await verify_signature(request, x_aura_timestamp, x_aura_signature)
    try:
        payload = ExecuteRequest.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid execution payload.") from exc

    canonical = json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    try:
        reservation = store.reserve(payload.idempotency_key, request_hash)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if reservation["state"] == "COMPLETED" and reservation.get("result"):
        return {**reservation["result"], "idempotent_replay": True}

    if not reservation.get("is_new") and reservation["state"] in {"PENDING", "UNKNOWN"}:
        recovered = broker.recover(payload.idempotency_key, payload)
        if recovered:
            store.complete(payload.idempotency_key, recovered)
            return {**recovered, "idempotent_replay": True}
        if reservation["state"] == "UNKNOWN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Execution state is unknown and no matching MT5 deal was recovered. Manual reconciliation is required.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An execution with this idempotency key is already in progress.",
        )

    try:
        result = broker.execute(payload)
        store.complete(payload.idempotency_key, result)
        return result
    except ValueError as exc:
        store.fail(payload.idempotency_key, str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        # order_send failures can be ambiguous at transport/process boundaries. The next
        # request with the same key attempts deal-history recovery before any resend.
        store.fail(payload.idempotency_key, str(exc), state="UNKNOWN")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/positions/close")
async def close_position(request: Request, x_aura_timestamp: str | None = Header(default=None), x_aura_signature: str | None = Header(default=None)):
    raw = await verify_signature(request, x_aura_timestamp, x_aura_signature)
    payload = CloseRequest.model_validate_json(raw)
    try:
        return broker.close(payload.ticket, payload.volume)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/positions/modify")
async def modify_position(request: Request, x_aura_timestamp: str | None = Header(default=None), x_aura_signature: str | None = Header(default=None)):
    raw = await verify_signature(request, x_aura_timestamp, x_aura_signature)
    payload = ModifyRequest.model_validate_json(raw)
    try:
        return broker.modify(payload.ticket, payload.sl, payload.tp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
