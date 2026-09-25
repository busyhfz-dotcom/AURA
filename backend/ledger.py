import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuraLedger:
    """Small durable ledger used for paper trading and execution audit.

    SQLite is intentionally used here so the terminal has persistence out of the box.
    Production deployments can migrate this interface to PostgreSQL without changing
    the API contract consumed by the frontend.
    """

    def __init__(self, path: str, starting_balance: float = 10_000.0):
        self.path = path
        self.starting_balance = float(starting_balance)
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
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS account_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    starting_balance REAL NOT NULL,
                    balance REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    broker_order_id TEXT,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    lots REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    sl REAL NOT NULL,
                    tp REAL NOT NULL,
                    risk_percent REAL NOT NULL,
                    message TEXT,
                    raw_payload TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    lots REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    sl REAL NOT NULL,
                    tp REAL NOT NULL,
                    risk_percent REAL NOT NULL,
                    status TEXT NOT NULL,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    FOREIGN KEY(order_id) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_requests (
                    idempotency_key TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    source TEXT NOT NULL,
                    bars INTEGER NOT NULL,
                    period_from TEXT NOT NULL,
                    period_to TEXT NOT NULL,
                    total_trades INTEGER NOT NULL,
                    total_return_percent REAL,
                    max_drawdown_percent REAL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
                CREATE INDEX IF NOT EXISTS idx_positions_opened_at ON positions(opened_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_execution_requests_updated ON execution_requests(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_backtests_created_at ON backtest_runs(created_at DESC);
                """
            )
            row = self._conn.execute("SELECT id FROM account_state WHERE id = 1").fetchone()
            if row is None:
                now = utc_now_iso()
                self._conn.execute(
                    "INSERT INTO account_state (id, starting_balance, balance, updated_at) VALUES (1, ?, ?, ?)",
                    (self.starting_balance, self.starting_balance, now),
                )

    def add_audit(self, event_type: str, message: str, severity: str = "info", metadata: Optional[dict] = None) -> str:
        event_id = f"EVT-{uuid.uuid4().hex[:12].upper()}"
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_events (id, event_type, severity, message, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, event_type, severity, message, json.dumps(metadata or {}), utc_now_iso()),
            )
        return event_id

    def reserve_execution_request(self, idempotency_key: str, request_hash: str) -> dict:
        key = (idempotency_key or "").strip()
        if not key:
            raise ValueError("Idempotency key is required.")
        if len(key) > 128:
            raise ValueError("Idempotency key is too long.")
        now = utc_now_iso()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM execution_requests WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                item = dict(row)
                if item["request_hash"] != request_hash:
                    raise ValueError("Idempotency key was already used for a different execution request.")
                if item.get("result_json"):
                    try:
                        item["result"] = json.loads(item["result_json"])
                    except json.JSONDecodeError:
                        item["result"] = None
                else:
                    item["result"] = None
                item["is_new"] = False
                return item

            self._conn.execute(
                """
                INSERT INTO execution_requests (
                    idempotency_key, request_hash, state, result_json,
                    error_message, created_at, updated_at
                ) VALUES (?, ?, 'PENDING', NULL, NULL, ?, ?)
                """,
                (key, request_hash, now, now),
            )
        return {
            "idempotency_key": key,
            "request_hash": request_hash,
            "state": "PENDING",
            "result": None,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
            "is_new": True,
        }

    def complete_execution_request(self, idempotency_key: str, result: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE execution_requests
                SET state = 'COMPLETED', result_json = ?, error_message = NULL, updated_at = ?
                WHERE idempotency_key = ?
                """,
                (json.dumps(result), utc_now_iso(), idempotency_key),
            )

    def fail_execution_request(self, idempotency_key: str, message: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE execution_requests
                SET state = 'FAILED', error_message = ?, updated_at = ?
                WHERE idempotency_key = ?
                """,
                (message, utc_now_iso(), idempotency_key),
            )

    def mark_execution_request_unknown(self, idempotency_key: str, message: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE execution_requests
                SET state = 'UNKNOWN', error_message = ?, updated_at = ?
                WHERE idempotency_key = ?
                """,
                (message, utc_now_iso(), idempotency_key),
            )

    def execution_request(self, idempotency_key: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM execution_requests WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        if item.get("result_json"):
            try:
                item["result"] = json.loads(item["result_json"])
            except json.JSONDecodeError:
                item["result"] = None
        else:
            item["result"] = None
        return item

    def record_execution(self, result: dict) -> dict:
        order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"
        created_at = utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO orders (
                    id, broker_order_id, mode, status, symbol, action, lots,
                    entry_price, sl, tp, risk_percent, message, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    str(result.get("order_id", "")),
                    result["mode"],
                    result["status"],
                    result["symbol"],
                    result["action"],
                    float(result["lots"]),
                    float(result["entry_price"]),
                    float(result["sl"]),
                    float(result["tp"]),
                    float(result["risk_percent"]),
                    result.get("message"),
                    json.dumps(result),
                    created_at,
                ),
            )

            position_id = None
            # Paper positions are owned by the local simulation ledger. Live positions
            # remain owned by MT5 and must be synchronized from the broker, never invented locally.
            if result["status"] == "PAPER_FILLED" and result.get("mode") == "paper":
                position_id = f"POS-{uuid.uuid4().hex[:12].upper()}"
                self._conn.execute(
                    """
                    INSERT INTO positions (
                        id, order_id, symbol, action, lots, entry_price, sl, tp,
                        risk_percent, status, opened_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
                    """,
                    (
                        position_id,
                        order_id,
                        result["symbol"],
                        result["action"],
                        float(result["lots"]),
                        float(result["entry_price"]),
                        float(result["sl"]),
                        float(result["tp"]),
                        float(result["risk_percent"]),
                        created_at,
                    ),
                )

        self.add_audit(
            "execution.accepted",
            f"{result['mode'].upper()} {result['action']} {result['symbol']} accepted.",
            metadata={"order_id": order_id, "position_id": position_id, "status": result["status"]},
        )
        return {"ledger_order_id": order_id, "position_id": position_id}

    def _paper_pnl(self, symbol: str, action: str, lots: float, entry: float, exit_price: float) -> float:
        direction = 1.0 if action == "BUY" else -1.0
        delta = (exit_price - entry) * direction
        symbol = symbol.upper()
        if symbol == "XAUUSD":
            return delta * 100.0 * lots
        if symbol == "USOIL":
            return delta * 1000.0 * lots
        if symbol in {"BTCUSD", "ETHUSD", "NAS100", "SP500"}:
            return delta * lots
        pnl_quote = delta * 100_000.0 * lots
        if symbol.endswith("JPY") and exit_price > 0:
            return pnl_quote / exit_price
        return pnl_quote

    def estimate_pnl(self, position: dict, mark_price: float) -> float:
        return round(self._paper_pnl(
            position["symbol"], position["action"], float(position["lots"]),
            float(position["entry_price"]), float(mark_price)
        ), 2)

    def close_position(self, position_id: str, exit_price: float, paper_only: bool = True) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
            if row is None:
                raise ValueError("Position not found.")
            if row["status"] != "OPEN":
                raise ValueError("Position is already closed.")
            order = self._conn.execute("SELECT mode FROM orders WHERE id = ?", (row["order_id"],)).fetchone()
            if paper_only and order and order["mode"] != "paper":
                raise ValueError("Live positions cannot be closed through the paper ledger endpoint.")

            pnl = self._paper_pnl(
                row["symbol"], row["action"], float(row["lots"]), float(row["entry_price"]), float(exit_price)
            )
            closed_at = utc_now_iso()
            with self._conn:
                self._conn.execute(
                    "UPDATE positions SET exit_price = ?, realized_pnl = ?, status = 'CLOSED', closed_at = ? WHERE id = ?",
                    (float(exit_price), round(pnl, 2), closed_at, position_id),
                )
                self._conn.execute(
                    "UPDATE account_state SET balance = balance + ?, updated_at = ? WHERE id = 1",
                    (round(pnl, 2), closed_at),
                )

        self.add_audit(
            "position.closed",
            f"Paper position {position_id} closed at market.",
            metadata={"position_id": position_id, "exit_price": exit_price, "realized_pnl": round(pnl, 2)},
        )
        return {"position_id": position_id, "status": "CLOSED", "exit_price": exit_price, "realized_pnl": round(pnl, 2)}

    def open_positions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM positions WHERE status = 'OPEN' ORDER BY opened_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_orders(self, limit: int = 12) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, broker_order_id, mode, status, symbol, action, lots, entry_price, sl, tp, risk_percent, message, created_at FROM orders ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def closed_positions(self, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, order_id, symbol, action, lots, entry_price, exit_price, sl, tp,
                       risk_percent, status, realized_pnl, opened_at, closed_at
                FROM positions
                WHERE status = 'CLOSED'
                ORDER BY closed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def performance_summary(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT realized_pnl, closed_at
                FROM positions
                WHERE status = 'CLOSED'
                ORDER BY closed_at ASC
                """
            ).fetchall()

        pnl_values = [float(row["realized_pnl"] or 0.0) for row in rows]
        wins = [value for value in pnl_values if value > 0]
        losses = [value for value in pnl_values if value < 0]
        breakeven = len(pnl_values) - len(wins) - len(losses)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        net_realized = sum(pnl_values)
        total = len(pnl_values)

        balance = self.starting_balance
        peak = balance
        max_drawdown_percent = 0.0
        equity_curve = []
        for row, pnl in zip(rows, pnl_values):
            balance += pnl
            peak = max(peak, balance)
            drawdown = ((peak - balance) / peak * 100.0) if peak > 0 else 0.0
            max_drawdown_percent = max(max_drawdown_percent, drawdown)
            equity_curve.append({
                "timestamp": row["closed_at"],
                "balance": round(balance, 2),
            })

        return {
            "closed_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": breakeven,
            "win_rate": round((len(wins) / total * 100.0), 2) if total else None,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "net_realized": round(net_realized, 2),
            "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
            "avg_win": round(gross_profit / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "expectancy": round(net_realized / total, 2) if total else None,
            "max_drawdown_percent": round(max_drawdown_percent, 2) if total else None,
            "equity_curve": equity_curve,
        }

    def record_backtest(self, result: dict) -> str:
        run_id = f"BT-{uuid.uuid4().hex[:12].upper()}"
        created_at = utc_now_iso()
        metrics = result.get("metrics") or {}
        payload = {**result, "id": run_id, "created_at": created_at}
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO backtest_runs (
                    id, strategy, strategy_version, symbol, timeframe, source, bars,
                    period_from, period_to, total_trades, total_return_percent,
                    max_drawdown_percent, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    result["strategy"],
                    result["strategy_version"],
                    result["symbol"],
                    result["timeframe"],
                    result["source"],
                    int(result["bars"]),
                    result["from"],
                    result["to"],
                    int(metrics.get("total_trades") or 0),
                    metrics.get("total_return_percent"),
                    metrics.get("max_drawdown_percent"),
                    json.dumps(payload),
                    created_at,
                ),
            )
        self.add_audit(
            "backtest.completed",
            f"Backtest {run_id} completed for {result['symbol']} {result['timeframe']}.",
            metadata={
                "run_id": run_id,
                "source": result["source"],
                "bars": result["bars"],
                "total_trades": metrics.get("total_trades", 0),
            },
        )
        return run_id

    def recent_backtests(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, strategy, strategy_version, symbol, timeframe, source, bars,
                       period_from, period_to, total_trades, total_return_percent,
                       max_drawdown_percent, created_at
                FROM backtest_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def backtest_run(self, run_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT result_json FROM backtest_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["result_json"])
        except json.JSONDecodeError:
            return None

    def recent_audit(self, limit: int = 30) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, event_type, severity, message, metadata, created_at FROM audit_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            result.append(item)
        return result

    def metrics(self) -> dict:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            account = self._conn.execute("SELECT * FROM account_state WHERE id = 1").fetchone()
            open_count = self._conn.execute("SELECT COUNT(*) AS c FROM positions WHERE status = 'OPEN'").fetchone()["c"]
            trades_today = self._conn.execute(
                "SELECT COUNT(*) AS c FROM orders WHERE substr(created_at, 1, 10) = ?", (today,)
            ).fetchone()["c"]
            realized_today = self._conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0) AS pnl FROM positions WHERE status = 'CLOSED' AND substr(closed_at, 1, 10) = ?",
                (today,),
            ).fetchone()["pnl"]
        return {
            "starting_balance": round(float(account["starting_balance"]), 2),
            "balance": round(float(account["balance"]), 2),
            "open_positions": int(open_count),
            "trades_today": int(trades_today),
            "realized_today": round(float(realized_today or 0), 2),
        }

    def symbol_has_open_position(self, symbol: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM positions WHERE status = 'OPEN' AND symbol = ? LIMIT 1", (symbol.upper(),)
            ).fetchone()
        return row is not None
