"""Scans the configured watchlist and turns raw TradeIdeas into sized,
budget-checked recommendations, capped at max_open_positions.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config import Config
from src.position_sizing import SizingResult, size_trade
from src.strategy import TradeIdea, evaluate_ticker


@dataclass
class ScreenResult:
    idea: TradeIdea
    sizing: SizingResult


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
            break
        sizing = size_trade(
            cost_per_contract=idea.cost_per_contract,
            portfolio_value=cfg.account.portfolio_value,
            max_risk_per_trade_pct=cfg.account.max_risk_per_trade_pct,
            max_trade_cost_usd=cfg.account.max_trade_cost_usd,
            committed_capital=committed,
        )
        if sizing.fits:
            accepted.append(ScreenResult(idea=idea, sizing=sizing))
            committed += sizing.total_cost

    return accepted, reasons
