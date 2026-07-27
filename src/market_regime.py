"""Broad-market direction check -- "don't fight the tape."

Skips ideas that bet against where the overall market itself is trending
that day, even if the individual ticker looks fine in isolation. Uses the
exact same trend signal (fast/slow SMA vs price) already used per-ticker,
just applied to a market-wide reference (SPY by default) instead of the
name being considered.
"""
from __future__ import annotations

from src import data as data_mod
from src import indicators
from src.config import Config


def get_market_direction(cfg: Config) -> str:
    """Returns 'bullish', 'bearish', or 'neutral'.

    'neutral' is also the fail-open value when the reference ticker's data
    can't be fetched -- a data hiccup here should never silently block
    every trade for the day.
    """
    ticker = cfg.market_regime.reference_ticker
    history = data_mod.get_price_history(ticker, period=cfg.data.price_history_period)
    if history.empty or len(history) < max(cfg.strategy.sma_slow, 60):
        return "neutral"
    return indicators.trend_signal(history, cfg.strategy.sma_fast, cfg.strategy.sma_slow)
