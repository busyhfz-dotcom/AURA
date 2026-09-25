import logging
import math
import uuid
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from config import Settings

logger = logging.getLogger("BrokerEngine")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 module is unavailable. Market data will use the simulation feed; "
        "live execution will remain disabled."
    )


@dataclass
class BrokerState:
    connected: bool
    provider: str
    reason: Optional[str]


class MT5ExecutionEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.connected = False
        self.connection_reason: Optional[str] = None
        self._initialize()

    def _initialize(self) -> None:
        if not MT5_AVAILABLE:
            self.connection_reason = "MetaTrader5 Python integration is unavailable on this runtime."
            return

        if not mt5.initialize():
            self.connection_reason = f"MT5 initialize failed: {mt5.last_error()}"
            logger.error(self.connection_reason)
            return

        credentials_present = all(
            [self.settings.mt5_account, self.settings.mt5_password, self.settings.mt5_server]
        )
        if credentials_present:
            logged_in = mt5.login(
                self.settings.mt5_account,
                password=self.settings.mt5_password,
                server=self.settings.mt5_server,
            )
            if not logged_in:
                self.connection_reason = f"MT5 login failed: {mt5.last_error()}"
                logger.error(self.connection_reason)
                return

        account = mt5.account_info()
        if account is None:
            self.connection_reason = "MT5 terminal initialized but no trading account is available."
            return

        self.connected = True
        self.connection_reason = None
        logger.info("MetaTrader5 connection established for account %s", account.login)

    @property
    def state(self) -> BrokerState:
        return BrokerState(
            connected=self.connected,
            provider="MetaTrader 5" if self.connected else "Simulation Feed",
            reason=self.connection_reason,
        )

    def get_market_candles(self, symbol: str, n_bars: int = 160) -> tuple[pd.DataFrame, str]:
        symbol = symbol.upper()
        if self.connected:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, n_bars)
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                return df[["time", "open", "high", "low", "close"]], "MT5"

        return self._simulation_candles(symbol, n_bars), "SIMULATION"

    def market_status(self, symbol: str, df: pd.DataFrame | None = None, source: str | None = None) -> dict:
        symbol = symbol.upper().strip()
        if df is None or df.empty:
            df, resolved_source = self.get_market_candles(symbol, n_bars=48)
            source = source or resolved_source
        source = source or ("MT5" if self.connected else "SIMULATION")

        if df.empty:
            return {
                "symbol": symbol,
                "source": source,
                "last_price": None,
                "bid": None,
                "ask": None,
                "spread": None,
                "spread_points": None,
                "volatility_percent": None,
                "volatility_state": "UNAVAILABLE",
            }

        last_price = float(df.iloc[-1]["close"])
        recent = df.tail(min(len(df), 20))
        mean_range = float((recent["high"] - recent["low"]).mean()) if len(recent) else 0.0
        volatility_percent = (mean_range / last_price * 100.0) if last_price else 0.0
        if volatility_percent < 0.04:
            volatility_state = "LOW"
        elif volatility_percent < 0.30:
            volatility_state = "NORMAL"
        else:
            volatility_state = "ELEVATED"

        bid = ask = spread = spread_points = None
        if self.connected and MT5_AVAILABLE:
            try:
                tick = mt5.symbol_info_tick(symbol)
                info = mt5.symbol_info(symbol)
                if tick is not None:
                    bid = float(tick.bid)
                    ask = float(tick.ask)
                    spread = max(0.0, ask - bid)
                    point = float(info.point) if info is not None and info.point else None
                    spread_points = (spread / point) if point else None
            except Exception as exc:
                logger.warning("Unable to read live quote metadata for %s: %s", symbol, exc)

        return {
            "symbol": symbol,
            "source": source,
            "last_price": round(last_price, 8),
            "bid": round(bid, 8) if bid is not None else None,
            "ask": round(ask, 8) if ask is not None else None,
            "spread": round(spread, 8) if spread is not None else None,
            "spread_points": round(spread_points, 2) if spread_points is not None else None,
            "volatility_percent": round(volatility_percent, 4),
            "volatility_state": volatility_state,
        }

    def _simulation_candles(self, symbol: str, n_bars: int) -> pd.DataFrame:
        # Deterministic per 15-minute bucket so the UI does not jump randomly on every poll.
        now = pd.Timestamp.now(tz="UTC").floor("15min")
        bucket_seed = int(now.timestamp() // 900)
        symbol_seed = sum(ord(char) for char in symbol)
        rng = np.random.default_rng(bucket_seed + symbol_seed)

        base_prices = {
            "EURUSD": 1.0845,
            "GBPUSD": 1.2615,
            "USDJPY": 149.21,
            "XAUUSD": 2336.40,
            "BTCUSD": 63450.0,
            "ETHUSD": 3412.30,
            "NAS100": 18420.0,
            "USOIL": 78.24,
            "SP500": 5422.10,
        }
        base = base_prices.get(symbol, 1.0)
        simulation_scales = {
            "EURUSD": 0.00028,
            "GBPUSD": 0.00032,
            "USDJPY": 0.035,
            "XAUUSD": 1.2,
            "BTCUSD": 115.0,
            "ETHUSD": 7.5,
            "NAS100": 22.0,
            "USOIL": 0.09,
            "SP500": 6.5,
        }
        scale = simulation_scales.get(symbol, 0.00028 if base < 10 else (0.035 if base < 500 else 1.2))

        dates = pd.date_range(end=now, periods=n_bars, freq="15min", tz="UTC")
        returns = rng.normal(0, scale, n_bars)
        close = base + np.cumsum(returns)
        wick = np.abs(rng.normal(scale * 0.72, scale * 0.3, n_bars))
        high = close + wick
        low = close - wick
        open_price = np.concatenate(([base], close[:-1]))

        return pd.DataFrame(
            {
                "time": dates,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            }
        )

    def _paper_volume(self, symbol: str, balance: float, risk_percent: float, entry: float, sl: float) -> float:
        stop_distance = abs(entry - sl)
        if stop_distance <= 0:
            raise ValueError("Stop loss must be different from entry price.")

        symbol = symbol.upper()
        risk_amount = balance * (risk_percent / 100.0)
        # Paper-mode contract assumptions are explicit and deterministic. Live sizing always
        # delegates to MT5 order_calc_profit and the broker's symbol metadata.
        if symbol in {"BTCUSD", "ETHUSD", "NAS100", "SP500"}:
            loss_per_lot = stop_distance
        elif symbol == "XAUUSD":
            loss_per_lot = stop_distance * 100.0
        elif symbol == "USOIL":
            loss_per_lot = stop_distance * 1000.0
        else:
            pip_size = 0.01 if symbol.endswith("JPY") else 0.0001
            pip_value_per_lot = 10.0
            loss_per_lot = (stop_distance / pip_size) * pip_value_per_lot
        volume = risk_amount / max(loss_per_lot, 0.01)
        return max(0.01, min(50.0, round(volume, 2)))

    def _live_volume(self, symbol: str, action: str, entry: float, sl: float, risk_percent: float) -> float:
        account = mt5.account_info()
        info = mt5.symbol_info(symbol)
        if account is None or info is None:
            raise RuntimeError("Unable to read MT5 account or symbol metadata.")

        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        loss_for_one_lot = mt5.order_calc_profit(order_type, symbol, 1.0, entry, sl)
        if loss_for_one_lot is None or loss_for_one_lot == 0:
            raise RuntimeError("MT5 could not calculate position risk for the requested stop loss.")

        risk_amount = account.balance * (risk_percent / 100.0)
        raw_volume = risk_amount / abs(loss_for_one_lot)
        step = info.volume_step or 0.01
        volume = math.floor(raw_volume / step) * step
        volume = max(info.volume_min, min(info.volume_max, volume))
        precision = max(0, int(round(-math.log10(step)))) if step < 1 else 0
        return round(volume, precision)

    def preview_position_size(
        self,
        symbol: str,
        action: str,
        entry: float,
        sl: float,
        risk_percent: float,
        balance: float,
    ) -> dict:
        symbol = symbol.upper().strip()
        action = action.upper().strip()
        if action not in {"BUY", "SELL"}:
            raise ValueError("Action must be BUY or SELL.")
        if entry <= 0 or sl <= 0:
            raise ValueError("Entry and stop loss must be positive values.")
        if entry == sl:
            raise ValueError("Stop loss must be different from entry price.")

        risk_percent = min(max(float(risk_percent), 0.1), self.settings.max_risk_percent)
        balance = max(float(balance), 0.0)
        risk_amount = balance * (risk_percent / 100.0)
        stop_distance = abs(entry - sl)
        pip_size = 0.01 if symbol.endswith("JPY") else (0.0001 if symbol.endswith("USD") and symbol not in {"XAUUSD", "BTCUSD", "ETHUSD"} else None)
        stop_pips = (stop_distance / pip_size) if pip_size else None
        estimated_margin = None

        if self.settings.live_execution_enabled and self.connected and MT5_AVAILABLE:
            volume = self._live_volume(symbol, action, entry, sl, risk_percent)
            try:
                order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
                margin = mt5.order_calc_margin(order_type, symbol, volume, entry)
                estimated_margin = float(margin) if margin is not None else None
            except Exception as exc:
                logger.warning("Unable to estimate margin for %s: %s", symbol, exc)
            basis = "MT5"
        else:
            volume = self._paper_volume(symbol, balance, risk_percent, entry, sl)
            basis = "PAPER_MODEL"

        return {
            "symbol": symbol,
            "action": action,
            "risk_percent": round(risk_percent, 3),
            "balance": round(balance, 2),
            "risk_amount": round(risk_amount, 2),
            "entry": entry,
            "sl": sl,
            "stop_distance": round(stop_distance, 8),
            "stop_pips": round(stop_pips, 2) if stop_pips is not None else None,
            "lots": volume,
            "estimated_margin": round(estimated_margin, 2) if estimated_margin is not None else None,
            "basis": basis,
        }

    def live_positions(self) -> list[dict]:
        if not self.connected or not MT5_AVAILABLE:
            return []
        positions = mt5.positions_get()
        if positions is None:
            raise RuntimeError(f"Unable to read MT5 positions: {mt5.last_error()}")
        return [
            {
                "ticket": position.ticket,
                "symbol": position.symbol,
                "volume": float(position.volume),
                "type": "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL",
                "price_open": float(position.price_open),
                "sl": float(position.sl),
                "tp": float(position.tp),
                "profit": float(position.profit),
            }
            for position in positions
        ]

    def has_live_position(self, symbol: str) -> bool:
        symbol = symbol.upper().strip()
        return any(position["symbol"].upper() == symbol for position in self.live_positions())

    def send_order(
        self,
        symbol: str,
        action: str,
        entry: float,
        sl: float,
        tp: float,
        risk_percent: float,
        paper_balance: float | None = None,
    ) -> dict:
        symbol = symbol.upper().strip()
        action = action.upper().strip()
        if action not in {"BUY", "SELL"}:
            raise ValueError("Action must be BUY or SELL.")
        if entry <= 0 or sl <= 0 or tp <= 0:
            raise ValueError("Entry, stop loss, and take profit must be positive values.")
        if action == "BUY" and not (sl < entry < tp):
            raise ValueError("BUY setup requires SL < entry < TP.")
        if action == "SELL" and not (tp < entry < sl):
            raise ValueError("SELL setup requires TP < entry < SL.")

        risk_percent = min(max(risk_percent, 0.1), self.settings.max_risk_percent)

        if not self.settings.live_execution_enabled:
            effective_balance = float(paper_balance) if paper_balance is not None else self.settings.paper_starting_balance
            volume = self._paper_volume(symbol, effective_balance, risk_percent, entry, sl)
            order_id = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
            logger.info("Paper order accepted: %s %s %s lots", action, symbol, volume)
            return {
                "status": "PAPER_FILLED",
                "mode": "paper",
                "order_id": order_id,
                "symbol": symbol,
                "action": action,
                "lots": volume,
                "entry_price": entry,
                "sl": sl,
                "tp": tp,
                "risk_percent": risk_percent,
                "message": "Paper execution completed. No live broker order was sent.",
            }

        if not self.connected:
            raise RuntimeError(
                "Live execution is enabled, but MetaTrader 5 is not connected. "
                f"{self.connection_reason or ''}".strip()
            )

        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Unable to select {symbol} in MetaTrader 5.")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No live tick is available for {symbol}.")

        market_price = tick.ask if action == "BUY" else tick.bid
        volume = self._live_volume(symbol, action, market_price, sl, risk_percent)
        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": market_price,
            "sl": sl,
            "tp": tp,
            "deviation": self.settings.mt5_deviation,
            "magic": 240300,
            "comment": "AURA Terminal",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        check = mt5.order_check(request)
        if check is None or check.retcode != 0:
            detail = getattr(check, "comment", "Unknown order check failure") if check else mt5.last_error()
            raise RuntimeError(f"MT5 order check failed: {detail}")

        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"MT5 order_send returned no result: {mt5.last_error()}")

        success_codes = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL}
        if result.retcode not in success_codes:
            raise RuntimeError(f"MT5 rejected the order ({result.retcode}): {result.comment}")

        logger.info("Live order filled: %s %s %s lots deal=%s", action, symbol, volume, result.deal)
        return {
            "status": "FILLED",
            "mode": "live",
            "order_id": result.order,
            "deal_id": result.deal,
            "symbol": symbol,
            "action": action,
            "lots": volume,
            "entry_price": result.price or market_price,
            "sl": sl,
            "tp": tp,
            "risk_percent": risk_percent,
            "message": "Order confirmed by MetaTrader 5.",
        }
