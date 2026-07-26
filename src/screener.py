"""Scans the configured watchlist and turns raw TradeIdeas into sized,
budget-checked recommendations, capped at max_open_positions.

Two extra passes beyond plain budget-fitting:
  - Diversification: a candidate is skipped if it's too correlated with an
    already-accepted idea in the same direction (see `max_correlation` in
    config.yaml) -- otherwise a small account's 3 open slots could all be
    the same bet wearing different tickers.
  - Confidence-weighted sizing: a cleaner setup (RSI centered in its band,
    volatility percentile with headroom under the cap) gets a bigger slice
    of the per-trade risk budget than a marginal one that just barely
    cleared the filters. See `confidence_size_floor_pct`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.config import Config
from src.position_sizing import SizingResult, size_trade
from src.strategy import TradeIdea, evaluate_ticker


@dataclass
class ScreenResult:
    idea: TradeIdea
    sizing: SizingResult


def _correlation(returns_a: list, returns_b: list, min_overlap: int = 20) -> float | None:
    """Pearson correlation over the overlapping trailing window, or None if
    there isn't enough data to trust a number."""
    n = min(len(returns_a), len(returns_b))
    if n < min_overlap:
        return None
    a = np.asarray(returns_a[-n:], dtype=float)
    b = np.asarray(returns_b[-n:], dtype=float)
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def run_screen(cfg: Config, verbose: bool = False) -> tuple[list[ScreenResult], dict]:
    """Returns (accepted_results, debug_reasons_by_ticker)."""
    candidates: list[TradeIdea] = []
    reasons: dict = {}

    for ticker in cfg.watchlist:
        idea, reason = evaluate_ticker(ticker, cfg)
        reasons[ticker] = reason
        if idea is not None:
            candidates.append(idea)
        if verbose:
            print(f"[{ticker}] {reason}")

    # Cheapest ideas first: on a small account, fitting more distinct trades
    # under the budget matters more than chasing the single "best" setup.
    candidates.sort(key=lambda i: i.cost_per_contract)

    accepted: list[ScreenResult] = []
    committed = 0.0

    for idea in candidates:
        if len(accepted) >= cfg.account.max_open_positions:
            reasons[idea.ticker] = "cleared strategy filters but max_open_positions already filled"
            continue

        correlated_with = None
        for a in accepted:
            if a.idea.direction != idea.direction:
                continue
            corr = _correlation(idea.recent_returns, a.idea.recent_returns)
            if corr is not None and corr >= cfg.account.max_correlation:
                correlated_with = (a.idea.ticker, corr)
                break
        if correlated_with is not None:
            other_ticker, corr = correlated_with
            reasons[idea.ticker] = (
                f"too correlated with already-picked {other_ticker} (ρ={corr:.2f}) "
                f"in the same direction, skipping for diversification"
            )
            continue

        floor = cfg.account.confidence_size_floor_pct
        scaled_risk_pct = cfg.account.max_risk_per_trade_pct * (floor + (1 - floor) * idea.confidence)

        sizing = size_trade(
            cost_per_contract=idea.cost_per_contract,
            portfolio_value=cfg.account.portfolio_value,
            max_risk_per_trade_pct=scaled_risk_pct,
            max_trade_cost_usd=cfg.account.max_trade_cost_usd,
            committed_capital=committed,
        )
        if sizing.fits:
            accepted.append(ScreenResult(idea=idea, sizing=sizing))
            committed += sizing.total_cost
        else:
            reasons[idea.ticker] = f"cleared strategy filters but didn't fit budget: {sizing.reason}"

    return accepted, reasons
