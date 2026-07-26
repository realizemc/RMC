"""Risk-based position sizing for a small account.

Options trade in lots of 100 shares, so sizing on a sub-$500 account is
usually a binary "1 contract or 0" decision rather than a smooth curve.
This module makes that decision explicit and rejects ideas that don't fit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SizingResult:
    fits: bool
    contracts: int
    cost_per_contract: float
    total_cost: float
    pct_of_portfolio: float
    reason: str


def size_trade(
    cost_per_contract: float,
    portfolio_value: float,
    max_risk_per_trade_pct: float,
    max_trade_cost_usd: float,
    committed_capital: float = 0.0,
) -> SizingResult:
    """cost_per_contract is the total debit for ONE contract (already x100),
    e.g. a $2.30 option premium = $230 per contract.

    `committed_capital` lets the caller account for money already tied up in
    other open ideas so we don't recommend spending money twice.
    """
    if cost_per_contract <= 0:
        return SizingResult(False, 0, cost_per_contract, 0.0, 0.0, "invalid contract cost")

    available = max(portfolio_value - committed_capital, 0.0)
    risk_budget = min(portfolio_value * max_risk_per_trade_pct, max_trade_cost_usd, available)

    contracts = math.floor(risk_budget / cost_per_contract)

    if contracts < 1:
        return SizingResult(
            fits=False,
            contracts=0,
            cost_per_contract=cost_per_contract,
            total_cost=0.0,
            pct_of_portfolio=0.0,
            reason=(
                f"1 contract costs ${cost_per_contract:.2f}, which exceeds the "
                f"${risk_budget:.2f} risk budget (available ${available:.2f})"
            ),
        )

    total_cost = contracts * cost_per_contract
    pct = total_cost / portfolio_value if portfolio_value else 0.0

    return SizingResult(
        fits=True,
        contracts=contracts,
        cost_per_contract=cost_per_contract,
        total_cost=total_cost,
        pct_of_portfolio=pct,
        reason="ok",
    )
