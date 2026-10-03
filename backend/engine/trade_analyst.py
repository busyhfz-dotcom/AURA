"""Multi-method trade analyst.

Combines structural analysis (SMC), multi-timeframe trend, momentum and
volume into one composite read per symbol — the way a discretionary
professional trader cross-checks several lenses before sizing a trade,
rather than firing off any single indicator in isolation.

Two rules make this behave like a risk-first trader rather than a signal
generator:
  1. Composite conviction has to clear a threshold before it becomes an
     actionable BUY/SELL — otherwise the honest answer is WAIT.
  2. Risk conditions (an active high-impact news embargo, or a HIGH
     composite risk score) override signal quality entirely. A good-looking
     setup inside a news embargo is still a WAIT.

The composite is an uncalibrated confluence score, never a win probability.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from engine import indicators as ind
from engine.confluence_engine import ConfluenceEngine

METHOD_WEIGHTS = {
    "structure": 0.35,
    "trend": 0.25,
    "momentum": 0.20,
    "volume": 0.20,
}

TREND_TIMEFRAMES = ("15m", "1h", "4h")
ACTIONABLE_THRESHOLD = 65.0  # composite % needed to call BUY/SELL instead of WAIT


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class TradeAnalyst:
    def __init__(self, confluence: ConfluenceEngine):
        self.confluence = confluence

    # ---- individual methods -------------------------------------------------

    def _structure_method(self, primary_df: pd.DataFrame, symbol: str) -> dict[str, Any]:
        setup = self.confluence.find_setup(primary_df, symbol)
        if setup["status"] == "A_PLUS_SETUP":
            lean = 1.0 if setup["action"] == "BUY" else -1.0
            confidence = setup["confluence_score"] / 100.0
            detail = f"Validated {setup['action']} structure (sweep + displacement + FVG), score {setup['confluence_score']}/100."
        elif setup["status"] == "SCANNING":
            sweep = self.confluence.detect_liquidity_sweep_and_mss(primary_df)
            if sweep.get("bullish_sweep"):
                lean = 1.0
            elif sweep.get("bearish_sweep"):
                lean = -1.0
            else:
                lean = 0.0
            confidence = 0.35 + (0.25 if sweep.get("displacement") else 0.0)
            detail = "Partial structure only (no confirmed entry trigger yet)." if lean != 0 else "No liquidity sweep detected; structure is neutral."
        else:
            lean, confidence, detail = 0.0, 0.0, "Not enough candle history to read structure."
        return {"lean": _clip(lean), "confidence": _clip(confidence, 0, 1), "detail": detail, "setup": setup}

    def _trend_method(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        directions: dict[str, int] = {}
        for tf in TREND_TIMEFRAMES:
            df = frames.get(tf)
            if df is None or len(df) < 210:
                continue
            e20 = ind.ema(df["close"], 20).iloc[-1]
            e50 = ind.ema(df["close"], 50).iloc[-1]
            e200 = ind.ema(df["close"], 200).iloc[-1]
            if e20 > e50 > e200:
                directions[tf] = 1
            elif e20 < e50 < e200:
                directions[tf] = -1
            else:
                directions[tf] = 0

        if not directions:
            return {"lean": 0.0, "confidence": 0.0, "detail": "Not enough history for a multi-timeframe trend read.", "by_timeframe": {}}

        lean = float(np.mean(list(directions.values())))
        confidence = sum(1 for v in directions.values() if v != 0) / len(TREND_TIMEFRAMES)
        labels = {tf: ("BULLISH" if d > 0 else "BEARISH" if d < 0 else "MIXED") for tf, d in directions.items()}
        detail = " · ".join(f"{tf}: {label}" for tf, label in labels.items())
        return {"lean": _clip(lean), "confidence": _clip(confidence, 0, 1), "detail": detail, "by_timeframe": labels}

    def _momentum_method(self, df: pd.DataFrame) -> dict[str, Any]:
        if len(df) < 40:
            return {"lean": 0.0, "confidence": 0.0, "detail": "Not enough history for momentum.", "rsi": None}

        rsi_value = float(ind.rsi(df["close"]).iloc[-1])
        macd = ind.macd(df["close"])
        hist = macd["histogram"]
        hist_now = float(hist.iloc[-1])
        hist_scale = float(hist.abs().rolling(20).mean().iloc[-1]) or 1e-9

        lean_rsi = _clip((rsi_value - 50.0) / 25.0)
        lean_macd = _clip(hist_now / (hist_scale + 1e-9))
        lean = (lean_rsi + lean_macd) / 2.0

        caution = None
        if rsi_value >= 72:
            caution = "RSI is overbought — a fresh long here is chasing extension, not confirming it."
        elif rsi_value <= 28:
            caution = "RSI is oversold — a fresh short here is chasing extension, not confirming it."

        detail = f"RSI {rsi_value:.1f}, MACD histogram {'rising' if hist_now >= 0 else 'falling'} ({hist_now:.5f})."
        return {"lean": lean, "confidence": 0.8, "detail": detail, "caution": caution, "rsi": round(rsi_value, 1)}

    def _volume_method(self, df: pd.DataFrame) -> dict[str, Any]:
        rel_vol = ind.relative_volume(df)
        obv_sl = ind.obv_slope(df)
        if rel_vol is None and obv_sl is None:
            return {"lean": 0.0, "confidence": 0.0, "detail": "No volume data available for this instrument.", "relative_volume": None}

        lean = _clip(obv_sl) if obv_sl is not None else 0.0
        if rel_vol is not None and rel_vol > 1.1:
            confidence = 0.75
        elif rel_vol is not None:
            confidence = 0.45
        else:
            confidence = 0.3
        detail = (
            f"Relative volume {rel_vol:.2f}x the 20-bar average, OBV slope {'up' if lean > 0 else 'down' if lean < 0 else 'flat'}."
            if rel_vol is not None
            else f"OBV slope {'up' if lean > 0 else 'down' if lean < 0 else 'flat'} (volume magnitude unavailable)."
        )
        return {"lean": lean, "confidence": confidence, "detail": detail, "relative_volume": round(rel_vol, 2) if rel_vol is not None else None}

    # ---- composite -------------------------------------------------------

    def analyze(
        self,
        symbol: str,
        frames: dict[str, pd.DataFrame],
        risk: dict[str, Any],
        news_guard: dict[str, Any],
    ) -> dict[str, Any]:
        primary = frames.get("15m", pd.DataFrame())

        structure = self._structure_method(primary, symbol)
        trend = self._trend_method(frames)
        momentum = self._momentum_method(primary) if not primary.empty else {"lean": 0.0, "confidence": 0.0, "detail": "No data.", "rsi": None}
        volume = self._volume_method(primary) if not primary.empty else {"lean": 0.0, "confidence": 0.0, "detail": "No data.", "relative_volume": None}

        methods = {"structure": structure, "trend": trend, "momentum": momentum, "volume": volume}
        net = sum(METHOD_WEIGHTS[name] * m["lean"] * m["confidence"] for name, m in methods.items())
        composite_bullish_percent = round(_clip(50.0 + 50.0 * net, 0, 100), 1)
        composite_bearish_percent = round(100.0 - composite_bullish_percent, 1)

        if composite_bullish_percent >= ACTIONABLE_THRESHOLD:
            raw_recommendation, probability_percent = "BUY", composite_bullish_percent
        elif composite_bearish_percent >= ACTIONABLE_THRESHOLD:
            raw_recommendation, probability_percent = "SELL", composite_bearish_percent
        else:
            raw_recommendation = "WAIT"
            probability_percent = max(composite_bullish_percent, composite_bearish_percent)

        # A directional technical lean alone is not an executable setup.
        override_reason = None
        override_code = None
        recommendation = raw_recommendation
        if primary.empty or any(frames.get(tf) is None or len(frames[tf]) < 210 for tf in TREND_TIMEFRAMES):
            recommendation = "WAIT"
            override_code = "INCOMPLETE_DATA"
            override_reason = "Complete 15m, 1h and 4h candle history is required before a trade call."
        elif news_guard.get("active"):
            recommendation = "WAIT"
            override_code = "NEWS_EMBARGO"
            override_reason = "High-impact economic news embargo is active — standing aside overrides the signal."
        elif not news_guard.get("configured") or news_guard.get("provider_error") or news_guard.get("safe") is not True:
            recommendation = "WAIT"
            override_code = "NEWS_UNKNOWN"
            override_reason = "Economic news status is unavailable; a clear calendar is required before a trade call."
        elif risk.get("risk_label") == "HIGH":
            recommendation = "WAIT"
            override_code = "HIGH_RISK"
            override_reason = "Composite market risk is HIGH — signal quality does not override risk conditions."
        elif structure["setup"].get("status") != "A_PLUS_SETUP" or structure["setup"].get("action") != recommendation:
            recommendation = "WAIT"
            override_code = "NO_ENTRY_TRIGGER"
            override_reason = "No confirmed structural entry trigger aligned with the directional read."

        entry_plan = self._entry_plan(primary, recommendation, structure["setup"], risk)

        suggested_risk_percent = self._suggested_risk(risk, recommendation)

        reasons = [methods["structure"]["detail"], methods["trend"]["detail"], methods["momentum"]["detail"], methods["volume"]["detail"]]
        if methods["momentum"].get("caution"):
            reasons.append(methods["momentum"]["caution"])
        if override_reason:
            reasons.append(override_reason)

        breakdown = [
            {
                "method": name.capitalize(),
                "weight_percent": round(METHOD_WEIGHTS[name] * 100),
                "lean": round(m["lean"], 2),
                "confidence_percent": round(m["confidence"] * 100),
                "detail": m["detail"],
            }
            for name, m in methods.items()
        ]

        return {
            "symbol": symbol,
            "recommendation": recommendation,
            "raw_recommendation": raw_recommendation,
            "probability_percent": probability_percent,
            "score_type": "UNCALIBRATED_CONFLUENCE",
            "calibrated_probability_percent": None,
            "composite_bullish_percent": composite_bullish_percent,
            "composite_bearish_percent": composite_bearish_percent,
            "override_reason": override_reason,
            "override_code": override_code,
            "entry_plan": entry_plan,
            "suggested_risk_percent": suggested_risk_percent,
            "risk_label": risk.get("risk_label"),
            "risk_score": risk.get("risk_score"),
            "method_breakdown": breakdown,
            "reasons": [r for r in reasons if r],
            "disclaimer": (
                "This is an uncalibrated technical confluence score, not a win probability or investment advice. "
                "No combination of indicators guarantees a profitable trade."
            ),
        }

    def _entry_plan(self, df: pd.DataFrame, direction: str, setup: dict[str, Any], risk: dict[str, Any]) -> Optional[dict[str, Any]]:
        if direction not in {"BUY", "SELL"} or df.empty or setup.get("status") != "A_PLUS_SETUP" or setup.get("action") != direction:
            return None

        if setup.get("status") == "A_PLUS_SETUP" and setup.get("action") == direction:
            return {
                "basis": "STRUCTURAL_TRIGGER",
                "entry": setup["entry"],
                "sl": setup["sl"],
                "tp": setup["tp"],
                "rr": setup.get("rr", "1:3.0"),
                "note": "A precise structural entry trigger (FVG midpoint) is already active for this direction.",
            }

        return None

    def _suggested_risk(self, risk: dict[str, Any], recommendation: str) -> float:
        if recommendation not in {"BUY", "SELL"}:
            return 0.0
        # An uncalibrated score cannot justify increasing position size.
        base = 0.5
        if risk.get("risk_label") == "ELEVATED":
            base *= 0.5
        elif risk.get("risk_label") == "MODERATE":
            base *= 0.8
        return round(base, 2)
