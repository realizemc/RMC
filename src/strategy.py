"""Core trade-idea generation.

For one ticker: read trend + RSI + a volatility-percentile proxy off daily
price history, and if they line up, pick a real contract (or two, for a
debit spread) off the live options chain that matches a target delta band,
passes liquidity filters, and fits inside the account's budget.

This module never talks to a broker. It produces `TradeIdea` objects that
`alerts.py` turns into human-readable output.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src import data as data_mod
from src import indicators
from src.config import Config
from src.options_pricing import bs_delta, implied_volatility


@dataclass
class OptionLeg:
    strike: float
    bid: float
    ask: float
    mid: float
    delta: float
    iv: float
    open_interest: int
    volume: int
    contract_symbol: str


@dataclass
class TradeIdea:
    ticker: str
    direction: str          # 'bullish' or 'bearish'
    structure: str          # 'long_call' | 'long_put' | 'call_debit_spread' | 'put_debit_spread'
    expiration: str
    dte: int
    underlying_price: float
    long_leg: OptionLeg
    short_leg: Optional[OptionLeg]
    cost_per_contract: float   # net debit, x100, for ONE contract
    max_loss_per_contract: float
    max_profit_per_contract: Optional[float]  # None means undefined/large (naked long option)
    breakeven: float
    iv_rank_proxy: float
    rsi: float
    rationale: str = field(default="")
    # Trailing daily returns of the underlying, used by the screener's
    # diversification check -- not fetched again, just carried along from
    # the price history this idea already pulled.
    recent_returns: list = field(default_factory=list)
    # 0-1 heuristic: how centered RSI is in its entry band + how much
    # headroom is left under the volatility-percentile cap. NOT a
    # probability of profit -- just used to scale position size a bit
    # bigger on stronger setups and smaller on marginal ones.
    confidence: float = 1.0


def _option_type_for_direction(direction: str) -> str:
    return "call" if direction == "bullish" else "put"


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _confidence_score(trend: str, rsi_val: float, iv_rank: float, cfg: Config) -> float:
    """0-1 heuristic blending how centered RSI is in its entry band with
    how much headroom is left under the volatility-percentile cap. This is
    NOT a probability of profit -- it's a rough "how clean is this setup"
    signal used only to scale position size a bit, never to gate a trade
    (that's what the hard filters upstream already do)."""
    if trend == "bullish":
        lo, hi = cfg.strategy.rsi_bull_min, cfg.strategy.rsi_bull_max
    else:
        lo, hi = cfg.strategy.rsi_bear_min, cfg.strategy.rsi_bear_max
    center, half = (lo + hi) / 2, (hi - lo) / 2
    rsi_confidence = _clip01(1 - abs(rsi_val - center) / half) if half > 0 else 1.0

    vol_confidence = (
        _clip01(1 - iv_rank / cfg.strategy.iv_rank_max_pct)
        if cfg.strategy.iv_rank_max_pct > 0 else 1.0
    )

    return (rsi_confidence + vol_confidence) / 2


def _liquid(row, cfg) -> bool:
    oi = row.get("openInterest", 0) or 0
    vol = row.get("volume", 0) or 0
    bid = row.get("bid", 0) or 0
    ask = row.get("ask", 0) or 0
    if oi < cfg.strategy.min_open_interest or vol < cfg.strategy.min_volume:
        return False
    if bid <= 0 or ask <= 0:
        return False
    mid = (bid + ask) / 2
    if mid <= 0:
        return False
    spread_pct = (ask - bid) / mid
    return spread_pct <= cfg.strategy.max_bid_ask_spread_pct


def _row_to_leg(row, S: float, T: float, r: float, option_type: str) -> Optional[OptionLeg]:
    bid = float(row.get("bid", 0) or 0)
    ask = float(row.get("ask", 0) or 0)
    mid = (bid + ask) / 2
    K = float(row["strike"])

    iv = row.get("impliedVolatility", None)
    if iv is None or iv != iv or iv <= 0:  # NaN check via iv != iv
        iv = implied_volatility(mid, S, K, T, r, option_type)
        if iv is None:
            return None

    delta = bs_delta(S, K, T, r, iv, option_type)

    return OptionLeg(
        strike=K,
        bid=bid,
        ask=ask,
        mid=mid,
        delta=delta,
        iv=float(iv),
        open_interest=int(row.get("openInterest", 0) or 0),
        volume=int(row.get("volume", 0) or 0),
        contract_symbol=str(row.get("contractSymbol", "")),
    )


def _pick_leg_by_delta(chain_df: pd.DataFrame, S, T, r, option_type, delta_min, delta_max, cfg):
    """Among liquid rows, return the leg whose |delta| is closest to the
    midpoint of [delta_min, delta_max]."""
    target = (delta_min + delta_max) / 2
    best = None
    best_dist = None
    for _, row in chain_df.iterrows():
        if not _liquid(row, cfg):
            continue
        leg = _row_to_leg(row, S, T, r, option_type)
        if leg is None:
            continue
        if not (delta_min <= abs(leg.delta) <= delta_max):
            continue
        dist = abs(abs(leg.delta) - target)
        if best is None or dist < best_dist:
            best, best_dist = leg, dist
    return best


def evaluate_ticker(ticker: str, cfg: Config) -> tuple[Optional[TradeIdea], str]:
    """Returns (TradeIdea or None, reason). Reason is always populated,
    even on success, for logging/debugging."""
    history = data_mod.get_price_history(ticker, period=cfg.data.price_history_period)
    if history.empty or len(history) < max(cfg.strategy.sma_slow, 60):
        return None, "insufficient price history"

    close = history["Close"]
    trend = indicators.trend_signal(history, cfg.strategy.sma_fast, cfg.strategy.sma_slow)
    if trend == "neutral":
        return None, "no clear trend (SMA fast/slow not aligned with price)"

    rsi_series = indicators.rsi(close, cfg.strategy.rsi_period)
    rsi_val = float(rsi_series.iloc[-1])

    if trend == "bullish":
        if not (cfg.strategy.rsi_bull_min <= rsi_val <= cfg.strategy.rsi_bull_max):
            return None, f"bullish trend but RSI {rsi_val:.1f} outside entry band"
    else:
        if not (cfg.strategy.rsi_bear_min <= rsi_val <= cfg.strategy.rsi_bear_max):
            return None, f"bearish trend but RSI {rsi_val:.1f} outside entry band"

    iv_rank = indicators.hv_percentile(close)
    if iv_rank is None:
        return None, "not enough history to estimate volatility percentile"
    if iv_rank > cfg.strategy.iv_rank_max_pct:
        return None, f"volatility percentile {iv_rank:.0f} too high to buy premium right now"

    S = float(close.iloc[-1])

    expirations = data_mod.expirations_in_dte_window(ticker, cfg.strategy.min_dte, cfg.strategy.max_dte)
    if not expirations:
        return None, "no expirations in target DTE window"

    target_dte = (cfg.strategy.min_dte + cfg.strategy.max_dte) / 2
    chosen_exp = None
    chosen_snapshot = None
    best_dte_dist = None
    for exp in expirations:
        snap = data_mod.get_option_chain(ticker, exp, underlying_price=S)
        if snap is None:
            continue
        dist = abs(snap.dte - target_dte)
        if best_dte_dist is None or dist < best_dte_dist:
            chosen_exp, chosen_snapshot, best_dte_dist = exp, snap, dist

    if chosen_snapshot is None:
        return None, "could not load an options chain for any candidate expiration"

    if cfg.strategy.avoid_earnings:
        exp_date = dt.datetime.strptime(chosen_exp, "%Y-%m-%d").date()
        earnings_date = data_mod.get_next_earnings_date(ticker)
        if earnings_date is not None and dt.date.today() <= earnings_date <= exp_date:
            return None, (
                f"earnings expected {earnings_date} falls before expiration {chosen_exp} "
                f"-- avoiding IV-crush risk"
            )

    option_type = _option_type_for_direction(trend)
    df = chosen_snapshot.calls if option_type == "call" else chosen_snapshot.puts
    if df.empty:
        return None, f"no {option_type} contracts returned for {chosen_exp}"

    T = max(chosen_snapshot.dte, 1) / 365.0
    r = data_mod.RISK_FREE_RATE

    long_leg = _pick_leg_by_delta(
        df, S, T, r, option_type,
        cfg.strategy.long_leg_delta_min, cfg.strategy.long_leg_delta_max, cfg,
    )
    if long_leg is None:
        return None, f"no liquid {option_type} in target delta band {cfg.strategy.long_leg_delta_min}-{cfg.strategy.long_leg_delta_max}"

    long_cost = long_leg.mid * 100

    # Try a debit spread if the plain long leg costs more than the account's
    # per-trade budget -- selling a further-OTM leg cuts cost at the expense
    # of capping upside.
    structure = f"long_{option_type}"
    short_leg = None
    cost_per_contract = long_cost
    max_profit = None  # undefined/large for a naked long option

    if long_cost > cfg.account.max_trade_cost_usd:
        short_leg = _pick_leg_by_delta(
            df, S, T, r, option_type,
            cfg.strategy.short_leg_delta_min, cfg.strategy.short_leg_delta_max, cfg,
        )
        is_valid_spread = (
            short_leg is not None
            and (
                (option_type == "call" and short_leg.strike > long_leg.strike)
                or (option_type == "put" and short_leg.strike < long_leg.strike)
            )
        )
        if is_valid_spread:
            structure = f"{option_type}_debit_spread"
            net_debit = long_leg.mid - short_leg.mid
            if net_debit <= 0:
                return None, "debit spread priced at zero/negative net debit, skipping (bad quote)"
            cost_per_contract = net_debit * 100
            width = abs(short_leg.strike - long_leg.strike)
            max_profit = (width * 100) - cost_per_contract
        else:
            short_leg = None  # fall back to reporting the plain long, even if pricey

    max_loss = cost_per_contract
    if option_type == "call":
        breakeven = long_leg.strike + (cost_per_contract / 100 if short_leg is None else (long_leg.mid - (short_leg.mid if short_leg else 0)))
    else:
        breakeven = long_leg.strike - (cost_per_contract / 100 if short_leg is None else (long_leg.mid - (short_leg.mid if short_leg else 0)))

    rationale_bits = [
        f"{trend} trend (price vs SMA{cfg.strategy.sma_fast}/{cfg.strategy.sma_slow})",
        f"RSI {rsi_val:.0f}",
        f"volatility percentile {iv_rank:.0f}/100 (not overpaying for premium)",
    ]
    if short_leg is not None:
        rationale_bits.append("built as a debit spread to fit your per-trade budget")

    recent_returns = close.pct_change().dropna().tail(60).tolist()
    confidence = _confidence_score(trend, rsi_val, iv_rank, cfg)

    idea = TradeIdea(
        ticker=ticker,
        direction=trend,
        structure=structure,
        expiration=chosen_exp,
        dte=chosen_snapshot.dte,
        underlying_price=S,
        long_leg=long_leg,
        short_leg=short_leg,
        cost_per_contract=cost_per_contract,
        max_loss_per_contract=max_loss,
        max_profit_per_contract=max_profit,
        breakeven=breakeven,
        iv_rank_proxy=iv_rank,
        rsi=rsi_val,
        rationale="; ".join(rationale_bits),
        recent_returns=recent_returns,
        confidence=confidence,
    )
    return idea, "ok"
