from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from engine.institutional_confluence import InstitutionalConfluenceEngine


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str
    timeframe: str = "M15"
    starting_balance: float = 10_000.0
    risk_percent: float = 1.0
    entry_wait_bars: int = 8
    max_hold_bars: int = 24
    warmup_bars: int = 40


class AuraBacktestEngine:
    """Deterministic event-based backtest for the AURA confluence engine.

    Signals are evaluated only with candles available at that historical point.
    Entry is treated as a pending FVG midpoint order for a limited number of bars.
    If SL and TP are both crossed inside one candle, the result is conservatively
    resolved as SL because intrabar sequencing is unavailable from OHLC data.
    """

    def __init__(self, confluence: InstitutionalConfluenceEngine):
        self.confluence = confluence

    @staticmethod
    def _r_multiple(action: str, entry: float, sl: float, exit_price: float) -> float:
        risk = abs(entry - sl)
        if risk <= 0:
            return 0.0
        move = (exit_price - entry) if action == "BUY" else (entry - exit_price)
        return move / risk

    @staticmethod
    def _touches_entry(row: pd.Series, entry: float) -> bool:
        return float(row["low"]) <= entry <= float(row["high"])

    @staticmethod
    def _resolve_exit(action: str, row: pd.Series, sl: float, tp: float) -> tuple[str | None, float | None]:
        high, low = float(row["high"]), float(row["low"])
        if action == "BUY":
            hit_sl, hit_tp = low <= sl, high >= tp
        else:
            hit_sl, hit_tp = high >= sl, low <= tp

        if hit_sl and hit_tp:
            return "SL", sl
        if hit_sl:
            return "SL", sl
        if hit_tp:
            return "TP", tp
        return None, None

    @staticmethod
    def _max_drawdown(equity: list[float]) -> float:
        if not equity:
            return 0.0
        peak = equity[0]
        max_dd = 0.0
        for value in equity:
            peak = max(peak, value)
            if peak > 0:
                max_dd = max(max_dd, (peak - value) / peak * 100.0)
        return max_dd

    def run(self, df: pd.DataFrame, config: BacktestConfig, source: str) -> dict[str, Any]:
        if df.empty or len(df) < max(config.warmup_bars + 10, 60):
            raise ValueError("Insufficient historical candles for backtesting.")

        work = df.sort_values("time").reset_index(drop=True).copy()
        balance = float(config.starting_balance)
        equity_curve = [{"time": work.iloc[config.warmup_bars - 1]["time"].isoformat(), "balance": round(balance, 2)}]
        trades: list[dict[str, Any]] = []
        i = config.warmup_bars

        while i < len(work) - 2:
            history_start = max(0, i - 220)
            history = work.iloc[history_start : i + 1]
            as_of = work.iloc[i]["time"]
            signal = self.confluence.find_high_probability_setup(history, config.symbol, as_of=as_of)

            if signal.get("status") != "A_PLUS_SETUP":
                i += 1
                continue

            action = signal["action"]
            entry = float(signal["entry"])
            sl = float(signal["sl"])
            tp = float(signal["tp"])
            if abs(entry - sl) <= 0:
                i += 1
                continue

            fill_index = None
            fill_deadline = min(len(work) - 1, i + config.entry_wait_bars)
            for j in range(i + 1, fill_deadline + 1):
                if self._touches_entry(work.iloc[j], entry):
                    fill_index = j
                    break

            if fill_index is None:
                i = fill_deadline + 1
                continue

            exit_index = None
            exit_reason = "TIME_EXIT"
            exit_price = None
            max_exit = min(len(work) - 1, fill_index + config.max_hold_bars)
            for j in range(fill_index, max_exit + 1):
                reason, price = self._resolve_exit(action, work.iloc[j], sl, tp)
                if reason:
                    exit_index, exit_reason, exit_price = j, reason, float(price)
                    break

            if exit_index is None:
                exit_index = max_exit
                exit_price = float(work.iloc[exit_index]["close"])

            r_multiple = self._r_multiple(action, entry, sl, float(exit_price))
            risk_amount = balance * (config.risk_percent / 100.0)
            pnl = risk_amount * r_multiple
            balance += pnl

            trade = {
                "symbol": config.symbol,
                "action": action,
                "signal_time": work.iloc[i]["time"].isoformat(),
                "entry_time": work.iloc[fill_index]["time"].isoformat(),
                "exit_time": work.iloc[exit_index]["time"].isoformat(),
                "entry": round(entry, 8),
                "sl": round(sl, 8),
                "tp": round(tp, 8),
                "exit_price": round(float(exit_price), 8),
                "exit_reason": exit_reason,
                "r_multiple": round(r_multiple, 4),
                "risk_amount": round(risk_amount, 2),
                "pnl": round(pnl, 2),
                "balance_after": round(balance, 2),
                "confluence_score": int(signal.get("confluence_score", 0)),
            }
            trades.append(trade)
            equity_curve.append({"time": trade["exit_time"], "balance": round(balance, 2)})
            i = exit_index + 1

        pnls = np.array([trade["pnl"] for trade in trades], dtype=float)
        r_values = np.array([trade["r_multiple"] for trade in trades], dtype=float)
        wins = int(np.sum(pnls > 0)) if len(pnls) else 0
        losses = int(np.sum(pnls < 0)) if len(pnls) else 0
        gross_profit = float(pnls[pnls > 0].sum()) if wins else 0.0
        gross_loss = abs(float(pnls[pnls < 0].sum())) if losses else 0.0
        total_return = ((balance - config.starting_balance) / config.starting_balance * 100.0) if config.starting_balance else 0.0
        returns = pnls / max(config.starting_balance, 1.0)
        sharpe = None
        if len(returns) >= 2 and float(np.std(returns, ddof=1)) > 0:
            sharpe = float(np.mean(returns) / np.std(returns, ddof=1) * math.sqrt(len(returns)))

        return {
            "strategy": "AURA Institutional Confluence",
            "symbol": config.symbol,
            "timeframe": config.timeframe,
            "source": source,
            "validation_level": "BROKER_HISTORICAL" if source == "MT5" else "SIMULATION_ONLY",
            "bars": len(work),
            "period": {
                "from": work.iloc[0]["time"].isoformat(),
                "to": work.iloc[-1]["time"].isoformat(),
            },
            "assumptions": {
                "starting_balance": round(config.starting_balance, 2),
                "risk_percent": round(config.risk_percent, 3),
                "entry_wait_bars": config.entry_wait_bars,
                "max_hold_bars": config.max_hold_bars,
                "same_bar_sl_tp_policy": "SL_FIRST_CONSERVATIVE",
                "commission_model": None,
                "slippage_model": None,
            },
            "metrics": {
                "ending_balance": round(balance, 2),
                "total_return_percent": round(total_return, 2),
                "total_trades": len(trades),
                "wins": wins,
                "losses": losses,
                "win_rate_percent": round((wins / len(trades) * 100.0), 2) if trades else None,
                "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else (None if not trades else None),
                "max_drawdown_percent": round(self._max_drawdown([point["balance"] for point in equity_curve]), 2),
                "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
                "avg_r_multiple": round(float(np.mean(r_values)), 3) if len(r_values) else None,
                "expectancy": round(float(np.mean(pnls)), 2) if len(pnls) else None,
                "net_pnl": round(float(pnls.sum()), 2) if len(pnls) else 0.0,
            },
            "equity_curve": equity_curve,
            "trades": trades[-200:],
        }
