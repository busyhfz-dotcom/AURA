"""Classic technical indicators, implemented directly on top of pandas.

Kept dependency-free (no ta-lib) so the container stays light. Every function
returns None/empty rather than a fabricated number when there isn't enough
history — the same no-invention rule as the rest of the platform.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    # A zero-loss uptrend is RSI 100, not neutral. Both sides zero is flat.
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    result = result.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    return result.fillna(50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, pd.Series]:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0) -> dict[str, pd.Series]:
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    return {"mid": mid, "upper": mid + num_std * std, "lower": mid - num_std * std}


def relative_volume(df: pd.DataFrame, period: int = 20) -> Optional[float]:
    if "volume" not in df.columns or df["volume"].isna().all() or len(df) < period + 1:
        return None
    baseline = df["volume"].iloc[-(period + 1):-1].mean()
    if not baseline or baseline <= 0:
        return None
    return float(df["volume"].iloc[-1] / baseline)


def obv_slope(df: pd.DataFrame, lookback: int = 10) -> Optional[float]:
    if "volume" not in df.columns or df["volume"].isna().all() or len(df) < lookback + 2:
        return None
    direction = np.sign(df["close"].diff()).fillna(0)
    obv = (direction * df["volume"]).cumsum()
    recent = obv.tail(lookback)
    if recent.iloc[0] == 0 and recent.iloc[-1] == 0:
        return 0.0
    # Normalize the slope by the recent OBV magnitude so it's comparable across symbols.
    span = max(abs(recent.max()), abs(recent.min()), 1.0)
    return float((recent.iloc[-1] - recent.iloc[0]) / span)


def swing_levels(df: pd.DataFrame, window: int = 8, lookback: int = 120) -> dict[str, Optional[float]]:
    """Nearest meaningful support/resistance from recent swing points."""
    if len(df) < window * 2 + 2:
        return {"support": None, "resistance": None}
    work = df.tail(min(len(df), lookback)).reset_index(drop=True)
    last_close = float(work["close"].iloc[-1])
    highs, lows = [], []
    for i in range(window, len(work) - window):
        window_slice = work.iloc[i - window : i + window + 1]
        if work["high"].iloc[i] == window_slice["high"].max():
            highs.append(float(work["high"].iloc[i]))
        if work["low"].iloc[i] == window_slice["low"].min():
            lows.append(float(work["low"].iloc[i]))

    resistance_candidates = [h for h in highs if h > last_close]
    support_candidates = [l for l in lows if l < last_close]
    return {
        "support": max(support_candidates) if support_candidates else None,
        "resistance": min(resistance_candidates) if resistance_candidates else None,
    }
