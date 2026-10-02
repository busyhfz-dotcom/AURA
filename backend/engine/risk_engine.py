"""Composite market-risk scoring.

Produces an explainable 0-100 risk score per symbol from measurable inputs
(realized volatility, 24h range, proximity to a high-impact news window,
active session). This is a risk *indicator*, not a promise: it never claims
to predict direction or outcome, only that current conditions are more or
less turbulent than the recent baseline.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def _volatility_percent(df: pd.DataFrame, window: int = 20) -> Optional[float]:
    if df.empty or len(df) < 5:
        return None
    recent = df.tail(min(len(df), window))
    last_price = float(df.iloc[-1]["close"])
    if last_price <= 0:
        return None
    mean_range = float((recent["high"] - recent["low"]).mean())
    return (mean_range / last_price) * 100.0


def _volatility_state(volatility_percent: Optional[float], asset_class: str) -> str:
    if volatility_percent is None:
        return "UNAVAILABLE"
    # Crypto is structurally more volatile than FX; thresholds are asset-aware.
    low, high = (0.15, 0.9) if asset_class == "CRYPTO" else (0.04, 0.30)
    if volatility_percent < low:
        return "LOW"
    if volatility_percent < high:
        return "NORMAL"
    return "ELEVATED"


class RiskEngine:
    def score(
        self,
        symbol: str,
        asset_class: str,
        df: pd.DataFrame,
        killzone_active: bool,
        news_active: bool,
        change_percent_24h: Optional[float] = None,
    ) -> dict[str, Any]:
        volatility_percent = _volatility_percent(df)
        volatility_state = _volatility_state(volatility_percent, asset_class)

        score = 0
        reasons: list[str] = []

        if volatility_state == "ELEVATED":
            score += 40
            reasons.append("Elevated short-term volatility versus recent baseline.")
        elif volatility_state == "NORMAL":
            score += 15
        elif volatility_state == "UNAVAILABLE":
            score += 10
            reasons.append("Insufficient data to measure volatility.")

        if change_percent_24h is not None:
            magnitude = abs(change_percent_24h)
            threshold = 5.0 if asset_class == "CRYPTO" else 0.8
            if magnitude >= threshold * 2:
                score += 25
                reasons.append(f"Large 24h move ({change_percent_24h:+.2f}%).")
            elif magnitude >= threshold:
                score += 12
                reasons.append(f"Above-average 24h move ({change_percent_24h:+.2f}%).")

        if news_active:
            score += 30
            reasons.append("Inside a high-impact economic news embargo window.")

        if killzone_active:
            score += 5
            reasons.append("Active institutional session (higher liquidity & higher variance).")

        score = max(0, min(100, score))
        if score >= 70:
            label = "HIGH"
        elif score >= 40:
            label = "ELEVATED"
        elif score >= 15:
            label = "MODERATE"
        else:
            label = "LOW"

        return {
            "symbol": symbol,
            "asset_class": asset_class,
            "risk_score": score,
            "risk_label": label,
            "volatility_percent": round(volatility_percent, 4) if volatility_percent is not None else None,
            "volatility_state": volatility_state,
            "news_embargo_active": news_active,
            "killzone_active": killzone_active,
            "change_percent_24h": change_percent_24h,
            "reasons": reasons,
        }
