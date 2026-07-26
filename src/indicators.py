"""Technical indicators and a historical-volatility-based IV-rank proxy.

We don't have a free source of historical option IV, so `hv_percentile`
approximates "IV rank" using where today's realized volatility sits within
the past year of rolling realized volatility. It's a proxy, not the real
thing -- documented clearly wherever it's used.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # avg_loss == 0: no down days in the lookback -> maximally overbought (100),
    # unless avg_gain is also 0 (flat price), which is genuinely neutral (50).
    out = out.where(avg_loss != 0, np.where(avg_gain > 0, 100.0, 50.0))
    out = pd.Series(out, index=series.index)
    return out


def realized_volatility(series: pd.Series, window: int = 20, trading_days: int = 252) -> pd.Series:
    """Annualized close-to-close realized volatility over a rolling window."""
    log_returns = np.log(series / series.shift(1))
    return log_returns.rolling(window=window, min_periods=window).std() * np.sqrt(trading_days)


def rolling_hv_percentile(series: pd.Series, hv_window: int = 20, lookback: int = 252) -> pd.Series:
    """Vectorized version of hv_percentile: at every row, where does that
    day's rolling realized vol sit within the trailing `lookback` days?
    Used by the backtester so we don't recompute from scratch per day."""
    hv = realized_volatility(series, window=hv_window)

    def _pct_of_last(window: np.ndarray) -> float:
        current = window[-1]
        if np.isnan(current):
            return np.nan
        valid = window[~np.isnan(window)]
        if len(valid) == 0:
            return np.nan
        return float((valid <= current).mean() * 100)

    return hv.rolling(window=lookback, min_periods=max(30, hv_window)).apply(_pct_of_last, raw=True)


def hv_percentile(series: pd.Series, hv_window: int = 20, lookback: int = 252) -> float | None:
    """Where does today's rolling realized vol sit vs the past `lookback` days?

    Returns a 0-100 percentile, or None if there isn't enough history.
    Used as a stand-in for IV rank: we prefer entering long-premium trades
    when this is NOT elevated (i.e. we're not overpaying for volatility).
    """
    hv = realized_volatility(series, window=hv_window)
    hv = hv.dropna()
    if len(hv) < max(30, hv_window):
        return None
    recent = hv.tail(lookback)
    current = recent.iloc[-1]
    pct = (recent <= current).mean() * 100
    return float(pct)


def trend_series(df: pd.DataFrame, sma_fast: int = 20, sma_slow: int = 50) -> pd.Series:
    """Vectorized per-row trend classification ('bullish'/'bearish'/'neutral')."""
    close = df["Close"]
    fast = sma(close, sma_fast)
    slow = sma(close, sma_slow)

    bullish = (close > slow) & (fast > slow)
    bearish = (close < slow) & (fast < slow)

    out = pd.Series("neutral", index=close.index)
    out[bullish] = "bullish"
    out[bearish] = "bearish"
    out[fast.isna() | slow.isna()] = "neutral"
    return out


def trend_signal(df: pd.DataFrame, sma_fast: int = 20, sma_slow: int = 50) -> str:
    """Returns 'bullish', 'bearish', or 'neutral' from a fast/slow SMA cross,
    for the most recent row only."""
    return trend_series(df, sma_fast, sma_slow).iloc[-1]
