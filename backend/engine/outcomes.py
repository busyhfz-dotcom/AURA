"""Conservative forward audit of archived trade calls against later closed bars.

This is an observation log, not a broker execution simulator. Intrabar order
is unknowable from OHLC, so a fill and an exit in one bar are ambiguous.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


BAR = timedelta(minutes=15)
FILL_BARS = 16
EXIT_BARS = 96


def audit_call(call: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    base = {"id": call["id"], "symbol": call["symbol"], "asset_class": call["asset_class"], "gross_r": None}
    direction = call["recommendation"]
    entry, stop, target = call.get("entry"), call.get("sl"), call.get("tp")
    if direction not in {"BUY", "SELL"} or any(v is None for v in (entry, stop, target)):
        return {**base, "status": "NO_PLAN"}
    if direction == "BUY" and not (stop < entry < target) or direction == "SELL" and not (target < entry < stop):
        return {**base, "status": "INVALID_PLAN"}
    called = datetime.fromisoformat(call["created_at"]).astimezone(timezone.utc)
    later = [bar for bar in bars if datetime.fromisoformat(bar["open_time"]).astimezone(timezone.utc) >= called]
    if not later:
        return {**base, "status": "PENDING"}
    if datetime.fromisoformat(later[0]["open_time"]).astimezone(timezone.utc) - called > 2 * BAR:
        return {**base, "status": "DATA_GAP"}
    filled_at = None
    for index, bar in enumerate(later):
        bar_time = datetime.fromisoformat(bar["open_time"]).astimezone(timezone.utc)
        if index and bar_time - datetime.fromisoformat(later[index - 1]["open_time"]).astimezone(timezone.utc) > BAR:
            return {**base, "status": "DATA_GAP"}
        if filled_at is None:
            if index >= FILL_BARS:
                return {**base, "status": "UNFILLED"}
            if bar["low"] <= entry <= bar["high"]:
                filled_at = index
                # The path inside the fill bar is unknowable from OHLC.
                if bar["low"] <= min(stop, target) or bar["high"] >= max(stop, target):
                    return {**base, "status": "AMBIGUOUS"}
            continue
        if index - filled_at > EXIT_BARS:
            return {**base, "status": "EXPIRED"}
        touched_stop = bar["low"] <= stop if direction == "BUY" else bar["high"] >= stop
        touched_target = bar["high"] >= target if direction == "BUY" else bar["low"] <= target
        if touched_stop and touched_target:
            return {**base, "status": "AMBIGUOUS"}
        if touched_stop:
            return {**base, "status": "LOSS", "gross_r": -1.0}
        if touched_target:
            return {**base, "status": "WIN", "gross_r": round(abs(target - entry) / abs(entry - stop), 4)}
    if filled_at is None and len(later) >= FILL_BARS:
        return {**base, "status": "UNFILLED"}
    if filled_at is not None and len(later) - filled_at > EXIT_BARS:
        return {**base, "status": "EXPIRED"}
    return {**base, "status": "PENDING"}
