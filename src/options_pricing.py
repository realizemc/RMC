"""Black-Scholes pricing, delta, and implied-vol solving.

Used for two things:
1. Filling in delta for real option chain rows (yfinance gives us IV but not
   greeks), so the strategy can pick strikes by delta band.
2. Repricing a hypothetical option day-by-day in the backtester.

This is a model, not the market. Real prices depend on the live bid/ask,
skew, and order flow -- Black-Scholes with a flat vol is a simplification
industry desks use as a starting point, not gospel.
"""
from __future__ import annotations

import math

from scipy.optimize import brentq
from scipy.stats import norm

MIN_T_YEARS = 1.0 / 365.0  # floor time-to-expiry to avoid div-by-zero on exp day


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float):
    T = max(T, MIN_T_YEARS)
    sigma = max(sigma, 1e-4)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """option_type: 'call' or 'put'. T in years."""
    T = max(T, MIN_T_YEARS)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    T = max(T, MIN_T_YEARS)
    d1, _ = _d1_d2(S, K, T, r, sigma)
    if option_type == "call":
        return float(norm.cdf(d1))
    return float(norm.cdf(d1) - 1.0)


def implied_volatility(
    price: float, S: float, K: float, T: float, r: float, option_type: str
) -> float | None:
    """Solve for sigma given an observed option price. Returns None if it
    can't be bracketed (e.g. price outside no-arbitrage bounds)."""
    T = max(T, MIN_T_YEARS)

    def f(sigma):
        return bs_price(S, K, T, r, sigma, option_type) - price

    try:
        return float(brentq(f, 1e-4, 5.0, maxiter=200))
    except ValueError:
        return None
