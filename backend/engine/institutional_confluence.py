from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd


class InstitutionalConfluenceEngine:
    def __init__(self, swing_window: int = 5, min_gap: float = 0.0004):
        self.swing_window = swing_window
        self.min_gap = min_gap

    def is_killzone_active(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        hour = now.hour + now.minute / 60.0
        london = 7.0 <= hour <= 10.0
        new_york = 13.0 <= hour <= 16.0
        return {
            "active": london or new_york,
            "session": "London Open" if london else ("New York AM" if new_york else "Off-Hours"),
        }

    def detect_liquidity_sweep_and_mss(self, df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 30:
            return {"sweep_detected": False, "displacement": False}

        k = self.swing_window
        work = df.copy()
        work["swing_high"] = False
        work["swing_low"] = False

        for i in range(k, len(work) - k):
            if work["high"].iloc[i] == work["high"].iloc[i - k : i + k + 1].max():
                work.at[work.index[i], "swing_high"] = True
            if work["low"].iloc[i] == work["low"].iloc[i - k : i + k + 1].min():
                work.at[work.index[i], "swing_low"] = True

        recent = work.iloc[-8:]
        prior = work.iloc[:-8]
        highs = prior[prior["swing_high"]]["high"]
        lows = prior[prior["swing_low"]]["low"]
        if highs.empty or lows.empty:
            return {"sweep_detected": False, "displacement": False}

        key_high = float(highs.iloc[-1])
        key_low = float(lows.iloc[-1])
        current_close = float(work["close"].iloc[-1])
        bearish_sweep = recent["high"].max() > key_high and current_close < key_high
        bullish_sweep = recent["low"].min() < key_low and current_close > key_low

        body_sizes = (work["close"] - work["open"]).abs()
        avg_body = float(body_sizes.rolling(20).mean().iloc[-1])
        current_body = abs(float(work["close"].iloc[-1] - work["open"].iloc[-1]))
        displacement = avg_body > 0 and current_body >= 1.8 * avg_body

        return {
            "bullish_sweep": bool(bullish_sweep),
            "bearish_sweep": bool(bearish_sweep),
            "displacement": bool(displacement),
            "key_high": key_high,
            "key_low": key_low,
        }

    @staticmethod
    def _score(checklist: dict) -> int:
        weights = {
            "sweep": 30,
            "displacement": 25,
            "fvg_midpoint": 25,
            "killzone_active": 20,
        }
        return sum(weight for key, weight in weights.items() if checklist.get(key))

    def find_high_probability_setup(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        killzone = self.is_killzone_active()
        if df.empty or len(df) < 30:
            return {
                "symbol": symbol,
                "status": "WAITING_FOR_DATA",
                "message": "At least 30 M15 candles are required before the engine can evaluate structure.",
                "confluence_score": 0,
                "checklist": {
                    "sweep": False,
                    "displacement": False,
                    "fvg_midpoint": False,
                    "killzone_active": killzone["active"],
                    "session_name": killzone["session"],
                },
            }

        sweep = self.detect_liquidity_sweep_and_mss(df)
        curr = df.iloc[-1]
        p_prev = df.iloc[-3]

        base_checklist = {
            "sweep": bool(sweep.get("bullish_sweep") or sweep.get("bearish_sweep")),
            "displacement": bool(sweep.get("displacement", False)),
            "fvg_midpoint": False,
            "killzone_active": killzone["active"],
            "session_name": killzone["session"],
        }

        if sweep.get("bullish_sweep") and sweep.get("displacement"):
            if float(curr["low"]) > float(p_prev["high"]) + self.min_gap:
                midpoint = (float(curr["low"]) + float(p_prev["high"])) / 2.0
                sl = float(sweep["key_low"])
                risk = midpoint - sl
                checklist = {**base_checklist, "fvg_midpoint": True}
                if risk > 0 and killzone["active"]:
                    return {
                        "symbol": symbol,
                        "status": "A_PLUS_SETUP",
                        "action": "BUY",
                        "session": killzone["session"],
                        "entry": round(midpoint, 5),
                        "entry_type": "FVG 50% Consequent Encroachment",
                        "sl": round(sl, 5),
                        "tp": round(midpoint + risk * 3.0, 5),
                        "rr": "1:3.0",
                        "confluence_score": self._score(checklist),
                        "checklist": checklist,
                    }
                base_checklist = checklist

        if sweep.get("bearish_sweep") and sweep.get("displacement"):
            if float(curr["high"]) < float(p_prev["low"]) - self.min_gap:
                midpoint = (float(p_prev["low"]) + float(curr["high"])) / 2.0
                sl = float(sweep["key_high"])
                risk = sl - midpoint
                checklist = {**base_checklist, "fvg_midpoint": True}
                if risk > 0 and killzone["active"]:
                    return {
                        "symbol": symbol,
                        "status": "A_PLUS_SETUP",
                        "action": "SELL",
                        "session": killzone["session"],
                        "entry": round(midpoint, 5),
                        "entry_type": "FVG 50% Consequent Encroachment",
                        "sl": round(sl, 5),
                        "tp": round(midpoint - risk * 3.0, 5),
                        "rr": "1:3.0",
                        "confluence_score": self._score(checklist),
                        "checklist": checklist,
                    }
                base_checklist = checklist

        return {
            "symbol": symbol,
            "status": "SCANNING",
            "message": "No fully validated setup is active. AURA is monitoring liquidity and displacement.",
            "confluence_score": self._score(base_checklist),
            "checklist": base_checklist,
        }
