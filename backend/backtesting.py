import math
import statistics
from dataclasses import dataclass
from typing import Any

import pandas as pd

from engine.institutional_confluence import InstitutionalConfluenceEngine


REQUIRED_COLUMNS = ("time", "open", "high", "low", "close")


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str
    timeframe: str = "M15"
    initial_balance: float = 10_000.0
    risk_percent: float = 0.5
    max_hold_bars: int = 96
    warmup_bars: int = 60


class HistoricalBacktestEngine:
    """Walk-forward evaluator for the same AURA confluence engine used by the terminal.

    The runner intentionally avoids synthetic market generation. It only accepts caller-
    supplied historical OHLC data or data fetched from a connected historical provider.
    One position is evaluated at a time and no trade is counted until a future candle
    actually touches the setup entry.
    """

    def __init__(self, strategy: InstitutionalConfluenceEngine):
        self.strategy = strategy

    @staticmethod
    def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            raise ValueError("Historical OHLC data is required.")
        missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
        if missing:
            raise ValueError(f"Historical data is missing required columns: {', '.join(missing)}")

        work = df.loc[:, list(REQUIRED_COLUMNS)].copy()
        work["time"] = pd.to_datetime(work["time"], utc=True, errors="coerce")
        for column in ("open", "high", "low", "close"):
            work[column] = pd.to_numeric(work[column], errors="coerce")
        work = work.dropna().sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
        if len(work) < 80:
            raise ValueError("At least 80 valid historical candles are required for a backtest.")
        invalid = work[
            (work["low"] > work["high"])
            | (work["open"] <= 0)
            | (work["high"] <= 0)
            | (work["low"] <= 0)
            | (work["close"] <= 0)
            | (work["open"] > work["high"])
            | (work["open"] < work["low"])
            | (work["close"] > work["high"])
            | (work["close"] < work["low"])
        ]
        if not invalid.empty:
            raise ValueError("Historical data contains invalid OHLC relationships.")
        return work

    @staticmethod
    def _hit(row: pd.Series, price: float) -> bool:
        return float(row["low"]) <= price <= float(row["high"])

    @staticmethod
    def _exit_hit(row: pd.Series, action: str, sl: float, tp: float) -> tuple[str | None, float | None]:
        low = float(row["low"])
        high = float(row["high"])
        if action == "BUY":
            sl_hit = low <= sl
            tp_hit = high >= tp
        else:
            sl_hit = high >= sl
            tp_hit = low <= tp

        # Intrabar sequencing is unknowable from OHLC. Use the conservative stop-first
        # assumption whenever both levels are inside the same candle.
        if sl_hit:
            return "SL", sl
        if tp_hit:
            return "TP", tp
        return None, None

    @staticmethod
    def _r_multiple(action: str, entry: float, sl: float, exit_price: float) -> float:
        risk_distance = abs(entry - sl)
        if risk_distance <= 0:
            return 0.0
        direction = 1.0 if action == "BUY" else -1.0
        return ((exit_price - entry) * direction) / risk_distance

    @staticmethod
    def _metrics(initial_balance: float, balance: float, trades: list[dict], equity_curve: list[dict]) -> dict:
        total = len(trades)
        winners = [trade for trade in trades if trade["pnl"] > 0]
        losers = [trade for trade in trades if trade["pnl"] < 0]
        gross_profit = sum(trade["pnl"] for trade in winners)
        gross_loss = abs(sum(trade["pnl"] for trade in losers))
        r_values = [float(trade["r_multiple"]) for trade in trades]
        pnl_returns = [float(trade["return_percent"]) / 100.0 for trade in trades]

        peak = initial_balance
        max_drawdown = 0.0
        for point in equity_curve:
            equity = float(point["balance"])
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)

        sharpe = None
        if len(pnl_returns) >= 2:
            deviation = statistics.stdev(pnl_returns)
            if deviation > 0:
                sharpe = statistics.mean(pnl_returns) / deviation * math.sqrt(len(pnl_returns))

        return {
            "initial_balance": round(initial_balance, 2),
            "ending_balance": round(balance, 2),
            "total_return_percent": round(((balance - initial_balance) / initial_balance) * 100.0, 3) if initial_balance else None,
            "total_trades": total,
            "wins": len(winners),
            "losses": len(losers),
            "win_rate": round((len(winners) / total) * 100.0, 2) if total else None,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
            "max_drawdown_percent": round(max_drawdown, 3) if equity_curve else None,
            "avg_r_multiple": round(statistics.mean(r_values), 3) if r_values else None,
            "expectancy_r": round(statistics.mean(r_values), 3) if r_values else None,
            "sharpe_trade_returns": round(sharpe, 3) if sharpe is not None else None,
        }

    def run(self, raw_df: pd.DataFrame, config: BacktestConfig, source: str) -> dict[str, Any]:
        df = self.normalize_bars(raw_df)
        symbol = config.symbol.upper().strip()
        initial_balance = float(config.initial_balance)
        if initial_balance <= 0:
            raise ValueError("Initial balance must be positive.")
        risk_percent = max(0.1, min(float(config.risk_percent), 2.0))
        max_hold = max(1, min(int(config.max_hold_bars), 500))
        warmup = max(30, min(int(config.warmup_bars), max(30, len(df) - 2)))

        balance = initial_balance
        trades: list[dict] = []
        equity_curve = [{"timestamp": df.iloc[0]["time"].isoformat(), "balance": round(balance, 2)}]
        index = warmup

        while index < len(df) - 1:
            history_start = max(0, index - 240)
            setup = self.strategy.find_high_probability_setup(df.iloc[history_start : index + 1].copy(), symbol)
            if setup.get("status") != "A_PLUS_SETUP":
                index += 1
                continue

            action = str(setup["action"])
            entry = float(setup["entry"])
            sl = float(setup["sl"])
            tp = float(setup["tp"])
            if action == "BUY" and not (sl < entry < tp):
                index += 1
                continue
            if action == "SELL" and not (tp < entry < sl):
                index += 1
                continue

            entry_index = None
            entry_limit = min(len(df), index + 1 + max_hold)
            for candidate in range(index + 1, entry_limit):
                if self._hit(df.iloc[candidate], entry):
                    entry_index = candidate
                    break
            if entry_index is None:
                index += 1
                continue

            exit_index = None
            exit_price = None
            exit_reason = None
            exit_limit = min(len(df), entry_index + max_hold + 1)
            for candidate in range(entry_index, exit_limit):
                reason, hit_price = self._exit_hit(df.iloc[candidate], action, sl, tp)
                if reason:
                    exit_index = candidate
                    exit_price = float(hit_price)
                    exit_reason = reason
                    break

            if exit_index is None:
                exit_index = exit_limit - 1
                exit_price = float(df.iloc[exit_index]["close"])
                exit_reason = "TIME_EXIT"

            r_multiple = self._r_multiple(action, entry, sl, exit_price)
            risk_amount = balance * (risk_percent / 100.0)
            pnl = risk_amount * r_multiple
            before = balance
            balance += pnl
            return_percent = (pnl / before * 100.0) if before else 0.0

            trade = {
                "number": len(trades) + 1,
                "symbol": symbol,
                "timeframe": config.timeframe,
                "action": action,
                "signal_time": df.iloc[index]["time"].isoformat(),
                "entry_time": df.iloc[entry_index]["time"].isoformat(),
                "exit_time": df.iloc[exit_index]["time"].isoformat(),
                "entry": round(entry, 8),
                "sl": round(sl, 8),
                "tp": round(tp, 8),
                "exit_price": round(exit_price, 8),
                "exit_reason": exit_reason,
                "risk_percent": round(risk_percent, 3),
                "r_multiple": round(r_multiple, 4),
                "pnl": round(pnl, 2),
                "return_percent": round(return_percent, 4),
                "balance_after": round(balance, 2),
                "confluence_score": int(setup.get("confluence_score", 0)),
                "session": setup.get("session"),
            }
            trades.append(trade)
            equity_curve.append({"timestamp": trade["exit_time"], "balance": trade["balance_after"]})
            index = exit_index + 1

        metrics = self._metrics(initial_balance, balance, trades, equity_curve)
        return {
            "strategy": "AURA Institutional Confluence",
            "strategy_version": "3.5",
            "symbol": symbol,
            "timeframe": config.timeframe,
            "source": source,
            "bars": len(df),
            "from": df.iloc[0]["time"].isoformat(),
            "to": df.iloc[-1]["time"].isoformat(),
            "assumptions": {
                "single_position": True,
                "entry_requires_future_touch": True,
                "intrabar_both_levels": "STOP_FIRST",
                "fees_and_slippage": "NOT_MODELED",
                "risk_percent": risk_percent,
                "max_hold_bars": max_hold,
            },
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": trades,
        }
