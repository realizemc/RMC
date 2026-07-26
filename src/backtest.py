"""A simplified historical backtest of the exact signal logic used live.

Important limitations, read before trusting the numbers:
  - There's no free historical options-chain data, so option prices are
    MODELED with Black-Scholes using (historical realized vol * a small
    multiplier) as a stand-in for implied vol. Real option prices reflect
    skew, term structure, and demand that this doesn't capture.
  - Only the plain long-call/long-put case is modeled (not debit spreads),
    since spread economics depend heavily on the vol surface, which we're
    already approximating.
  - Fills are at the model's mid price with no slippage or commissions.
  - Trend/RSI/volatility-percentile signals ARE the real, exact functions
    used by the live screener, just evaluated on historical data.

Treat results as "does this entry logic have positive expectancy", not
"this is what your account would have actually done."
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src import data as data_mod
from src import indicators
from src.config import Config
from src.options_pricing import bs_delta, bs_price
from src.position_sizing import size_trade


@dataclass
class Trade:
    ticker: str
    direction: str
    option_type: str
    structure: str
    entry_date: str
    exit_date: str
    strike: float
    short_strike: float | None
    sigma: float
    entry_price: float
    exit_price: float
    contracts: int
    cost_total: float
    pnl_total: float
    pnl_pct: float
    exit_reason: str
    hold_days: int


@dataclass
class OpenPosition:
    ticker: str
    direction: str
    option_type: str
    structure: str
    entry_date: pd.Timestamp
    strike: float
    short_strike: float | None
    sigma: float
    entry_price: float          # net debit per share (long - short, or just long)
    total_dte: int
    contracts: int
    cost_total: float


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)  # list of (date, equity)
    starting_capital: float = 0.0
    ending_equity: float = 0.0

    @property
    def total_return_pct(self) -> float:
        if not self.starting_capital:
            return 0.0
        return (self.ending_equity - self.starting_capital) / self.starting_capital

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = [t for t in self.trades if t.pnl_total > 0]
        return len(wins) / len(self.trades)

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = -float("inf")
        max_dd = 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            if peak > 0:
                max_dd = min(max_dd, (eq - peak) / peak)
        return max_dd


def _find_strike_for_delta(S, T, r, sigma, option_type, target_delta):
    strikes = np.linspace(S * 0.5, S * 1.5, 201)
    best_k, best_dist = None, None
    for K in strikes:
        d = bs_delta(S, K, T, r, sigma, option_type)
        dist = abs(abs(d) - target_delta)
        if best_dist is None or dist < best_dist:
            best_k, best_dist = K, dist
    return float(best_k)


def _position_value(S_t, T, r, pos) -> float:
    """Per-share value of an open position (long leg minus short leg, if any)
    at underlying price S_t with T years remaining."""
    if T <= 0:
        long_val = max(S_t - pos.strike, 0.0) if pos.option_type == "call" else max(pos.strike - S_t, 0.0)
        short_val = 0.0
        if pos.short_strike is not None:
            short_val = max(S_t - pos.short_strike, 0.0) if pos.option_type == "call" else max(pos.short_strike - S_t, 0.0)
        return long_val - short_val

    long_val = bs_price(S_t, pos.strike, T, r, pos.sigma, pos.option_type)
    if pos.short_strike is None:
        return long_val
    short_val = bs_price(S_t, pos.short_strike, T, r, pos.sigma, pos.option_type)
    return long_val - short_val


def _build_signal_frame(ticker: str, cfg: Config, years: int) -> pd.DataFrame | None:
    history = data_mod.get_price_history(ticker, period=f"{years + 1}y")
    if history.empty or len(history) < max(cfg.strategy.sma_slow, 60) + 30:
        return None

    close = history["Close"]
    df = pd.DataFrame(index=history.index)
    df["close"] = close
    df["trend"] = indicators.trend_series(close.to_frame(name="Close"), cfg.strategy.sma_fast, cfg.strategy.sma_slow)
    df["rsi"] = indicators.rsi(close, cfg.strategy.rsi_period)
    df["hv20"] = indicators.realized_volatility(close, window=20)
    df["hv_pct"] = indicators.rolling_hv_percentile(close)

    cutoff = df.index[-1] - pd.Timedelta(days=365 * years)
    return df[df.index >= cutoff]


def run_backtest(cfg: Config, tickers: list | None = None, years: int = 3, vol_multiplier: float = 1.15) -> BacktestResult:
    tickers = tickers or cfg.watchlist
    r = data_mod.RISK_FREE_RATE
    target_dte = int((cfg.strategy.min_dte + cfg.strategy.max_dte) / 2)
    target_delta = (cfg.strategy.long_leg_delta_min + cfg.strategy.long_leg_delta_max) / 2

    signal_frames = {}
    for t in tickers:
        sf = _build_signal_frame(t, cfg, years)
        if sf is not None:
            signal_frames[t] = sf

    if not signal_frames:
        return BacktestResult(starting_capital=cfg.account.portfolio_value, ending_equity=cfg.account.portfolio_value)

    all_dates = sorted(set().union(*(set(df.index) for df in signal_frames.values())))

    cash = cfg.account.portfolio_value
    open_positions: dict[str, OpenPosition] = {}
    trades: list[Trade] = []
    equity_curve = []

    short_target_delta = (cfg.strategy.short_leg_delta_min + cfg.strategy.short_leg_delta_max) / 2

    for d in all_dates:
        # --- mark-to-market + exit checks for open positions ---
        for ticker in list(open_positions.keys()):
            pos = open_positions[ticker]
            sf = signal_frames[ticker]
            if d not in sf.index:
                continue
            S_t = float(sf.loc[d, "close"])
            days_elapsed = (d - pos.entry_date).days
            dte_remaining = pos.total_dte - days_elapsed
            is_last_date = d == all_dates[-1]
            T = max(dte_remaining, 0) / 365.0
            value = _position_value(S_t, T, r, pos)

            if dte_remaining <= 0:
                reason = "expired"
            else:
                pnl_pct = (value - pos.entry_price) / pos.entry_price if pos.entry_price else 0.0
                reason = None
                if pnl_pct >= cfg.exits.profit_target_pct:
                    reason = "profit_target"
                elif pnl_pct <= -cfg.exits.stop_loss_pct:
                    reason = "stop_loss"
                elif dte_remaining <= cfg.exits.close_by_dte:
                    reason = "time_exit"
                elif is_last_date:
                    reason = "backtest_end"

            if reason is not None:
                exit_price = value
                pnl_per_contract = (exit_price - pos.entry_price) * 100
                pnl_total = pnl_per_contract * pos.contracts
                cash += max(exit_price, 0.0) * 100 * pos.contracts
                trades.append(Trade(
                    ticker=ticker,
                    direction=pos.direction,
                    option_type=pos.option_type,
                    structure=pos.structure,
                    entry_date=pos.entry_date.date().isoformat(),
                    exit_date=d.date().isoformat(),
                    strike=pos.strike,
                    short_strike=pos.short_strike,
                    sigma=pos.sigma,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    contracts=pos.contracts,
                    cost_total=pos.cost_total,
                    pnl_total=pnl_total,
                    pnl_pct=(exit_price - pos.entry_price) / pos.entry_price if pos.entry_price else 0.0,
                    exit_reason=reason,
                    hold_days=days_elapsed,
                ))
                del open_positions[ticker]

        # --- look for new entries ---
        if len(open_positions) < cfg.account.max_open_positions:
            for ticker, sf in signal_frames.items():
                if ticker in open_positions or d not in sf.index:
                    continue
                if len(open_positions) >= cfg.account.max_open_positions:
                    break
                row = sf.loc[d]
                trend = row["trend"]
                if trend not in ("bullish", "bearish"):
                    continue
                rsi_val, hv20, hv_pct = row["rsi"], row["hv20"], row["hv_pct"]
                if pd.isna(hv20) or pd.isna(hv_pct):
                    continue
                if trend == "bullish":
                    if not (cfg.strategy.rsi_bull_min <= rsi_val <= cfg.strategy.rsi_bull_max):
                        continue
                else:
                    if not (cfg.strategy.rsi_bear_min <= rsi_val <= cfg.strategy.rsi_bear_max):
                        continue
                if hv_pct > cfg.strategy.iv_rank_max_pct:
                    continue

                S = float(row["close"])
                sigma = max(hv20 * vol_multiplier, 0.05)
                option_type = "call" if trend == "bullish" else "put"
                T = target_dte / 365.0
                K = _find_strike_for_delta(S, T, r, sigma, option_type, target_delta)
                long_price = bs_price(S, K, T, r, sigma, option_type)
                if long_price <= 0.01:
                    continue

                # Mirrors the live strategy: if the plain long leg costs more
                # than the per-trade budget, convert to a debit spread by
                # selling a further-OTM leg to bring the cost down.
                structure = f"long_{option_type}"
                short_strike = None
                entry_price = long_price
                if long_price * 100 > cfg.account.max_trade_cost_usd:
                    short_K = _find_strike_for_delta(S, T, r, sigma, option_type, short_target_delta)
                    is_valid_spread = (
                        (option_type == "call" and short_K > K)
                        or (option_type == "put" and short_K < K)
                    )
                    if is_valid_spread:
                        short_price = bs_price(S, short_K, T, r, sigma, option_type)
                        net_debit = long_price - short_price
                        if net_debit > 0.01:
                            structure = f"{option_type}_debit_spread"
                            short_strike = short_K
                            entry_price = net_debit

                cost_per_contract = entry_price * 100

                committed = sum(p.cost_total for p in open_positions.values())
                portfolio_value_now = cash + committed
                sizing = size_trade(
                    cost_per_contract=cost_per_contract,
                    portfolio_value=portfolio_value_now,
                    max_risk_per_trade_pct=cfg.account.max_risk_per_trade_pct,
                    max_trade_cost_usd=cfg.account.max_trade_cost_usd,
                    committed_capital=committed,
                )
                if not sizing.fits or sizing.total_cost > cash:
                    continue

                cash -= sizing.total_cost
                open_positions[ticker] = OpenPosition(
                    ticker=ticker,
                    direction=trend,
                    option_type=option_type,
                    structure=structure,
                    entry_date=d,
                    strike=K,
                    short_strike=short_strike,
                    sigma=sigma,
                    entry_price=entry_price,
                    total_dte=target_dte,
                    contracts=sizing.contracts,
                    cost_total=sizing.total_cost,
                )

        # --- equity snapshot for the day ---
        mtm = 0.0
        for ticker, pos in open_positions.items():
            sf = signal_frames[ticker]
            if d in sf.index:
                S_t = float(sf.loc[d, "close"])
                days_elapsed = (d - pos.entry_date).days
                dte_remaining = max(pos.total_dte - days_elapsed, 0)
                T = dte_remaining / 365.0
                v = _position_value(S_t, T, r, pos)
                mtm += v * 100 * pos.contracts
            else:
                mtm += pos.cost_total
        equity_curve.append((d.date().isoformat(), cash + mtm))

    ending_equity = equity_curve[-1][1] if equity_curve else cfg.account.portfolio_value

    return BacktestResult(
        trades=trades,
        equity_curve=equity_curve,
        starting_capital=cfg.account.portfolio_value,
        ending_equity=ending_equity,
    )


def summarize(result: BacktestResult) -> str:
    lines = []
    lines.append(f"Starting capital : ${result.starting_capital:.2f}")
    lines.append(f"Ending equity    : ${result.ending_equity:.2f}")
    lines.append(f"Total return     : {result.total_return_pct * 100:+.1f}%")
    lines.append(f"Total trades     : {len(result.trades)}")
    lines.append(f"Win rate         : {result.win_rate * 100:.0f}%")
    lines.append(f"Max drawdown     : {result.max_drawdown_pct * 100:.1f}%")
    if result.trades:
        avg_pnl_pct = sum(t.pnl_pct for t in result.trades) / len(result.trades)
        avg_hold = sum(t.hold_days for t in result.trades) / len(result.trades)
        lines.append(f"Avg trade return : {avg_pnl_pct * 100:+.1f}%")
        lines.append(f"Avg hold (days)  : {avg_hold:.0f}")
        reasons = {}
        for t in result.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        lines.append(f"Exit reasons     : {reasons}")
    return "\n".join(lines)
