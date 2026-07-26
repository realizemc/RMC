"""Thin wrappers around yfinance for price history and options chains.

All network calls are isolated here so the rest of the system can be
unit-tested against plain DataFrames without hitting the network.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf

# Approximate short-term risk-free rate used for Black-Scholes / delta calcs.
# Not fetched live -- it's a minor input for near-dated options, hardcoding
# is fine and avoids another network dependency. Update occasionally.
RISK_FREE_RATE = 0.045


@dataclass
class OptionChainSnapshot:
    ticker: str
    underlying_price: float
    expiration: str
    dte: int
    calls: pd.DataFrame
    puts: pd.DataFrame


def get_price_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Daily OHLCV history for `ticker`. Returns empty DataFrame on failure."""
    try:
        hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    except Exception:
        return pd.DataFrame()
    if hist is None or hist.empty:
        return pd.DataFrame()
    hist = hist.dropna(subset=["Close"])
    return hist


def get_current_price(ticker: str, history: Optional[pd.DataFrame] = None) -> Optional[float]:
    if history is None:
        history = get_price_history(ticker, period="5d")
    if history is None or history.empty:
        return None
    return float(history["Close"].iloc[-1])


def list_expirations(ticker: str) -> list:
    try:
        return list(yf.Ticker(ticker).options)
    except Exception:
        return []


def get_option_chain(ticker: str, expiration: str, underlying_price: Optional[float] = None) -> Optional[OptionChainSnapshot]:
    """Fetch the calls/puts chain for one expiration date (YYYY-MM-DD)."""
    tk = yf.Ticker(ticker)
    try:
        chain = tk.option_chain(expiration)
    except Exception:
        return None

    if underlying_price is None:
        underlying_price = get_current_price(ticker)
    if underlying_price is None:
        return None

    exp_date = dt.datetime.strptime(expiration, "%Y-%m-%d").date()
    dte = (exp_date - dt.date.today()).days

    return OptionChainSnapshot(
        ticker=ticker,
        underlying_price=underlying_price,
        expiration=expiration,
        dte=dte,
        calls=chain.calls.copy(),
        puts=chain.puts.copy(),
    )


def expirations_in_dte_window(ticker: str, min_dte: int, max_dte: int) -> list:
    """Return expiration date strings whose DTE falls in [min_dte, max_dte]."""
    today = dt.date.today()
    out = []
    for exp in list_expirations(ticker):
        try:
            exp_date = dt.datetime.strptime(exp, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp_date - today).days
        if min_dte <= dte <= max_dte:
            out.append((exp, dte))
    out.sort(key=lambda x: x[1])
    return [exp for exp, _ in out]
