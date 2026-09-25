from dataclasses import dataclass

from ledger import AuraLedger


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    code: str
    message: str


class RiskGuard:
    def __init__(
        self,
        ledger: AuraLedger,
        max_open_positions: int,
        max_trades_per_day: int,
        max_daily_loss_percent: float,
        prevent_duplicate_symbol: bool = True,
    ):
        self.ledger = ledger
        self.max_open_positions = max_open_positions
        self.max_trades_per_day = max_trades_per_day
        self.max_daily_loss_percent = max_daily_loss_percent
        self.prevent_duplicate_symbol = prevent_duplicate_symbol

    def evaluate(self, symbol: str) -> RiskDecision:
        metrics = self.ledger.metrics()
        if metrics["open_positions"] >= self.max_open_positions:
            return RiskDecision(False, "MAX_OPEN_POSITIONS", "Maximum concurrent position limit reached.")

        if metrics["trades_today"] >= self.max_trades_per_day:
            return RiskDecision(False, "MAX_DAILY_TRADES", "Daily execution limit reached.")

        max_loss_amount = metrics["starting_balance"] * (self.max_daily_loss_percent / 100.0)
        if metrics["realized_today"] <= -max_loss_amount:
            return RiskDecision(False, "DAILY_LOSS_LIMIT", "Daily realized loss guard is active.")

        if self.prevent_duplicate_symbol and self.ledger.symbol_has_open_position(symbol):
            return RiskDecision(False, "DUPLICATE_SYMBOL", f"An open {symbol.upper()} position already exists.")

        return RiskDecision(True, "OK", "Risk guard approved the execution request.")

    def status(self) -> dict:
        metrics = self.ledger.metrics()
        max_loss_amount = metrics["starting_balance"] * (self.max_daily_loss_percent / 100.0)
        return {
            "state": "READY" if metrics["realized_today"] > -max_loss_amount else "LOCKED",
            "max_open_positions": self.max_open_positions,
            "max_trades_per_day": self.max_trades_per_day,
            "max_daily_loss_percent": self.max_daily_loss_percent,
            "duplicate_symbol_protection": self.prevent_duplicate_symbol,
            "metrics": metrics,
        }
