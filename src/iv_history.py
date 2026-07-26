"""Logs real, observed at-the-money implied volatility for every watchlist
ticker once per run, regardless of whether that ticker produces a trade
idea that day.

Why: `indicators.hv_percentile` is only a realized-volatility-based PROXY
for IV rank, because there's no free source of historical implied
volatility. This module builds that missing history ourselves, one
snapshot at a time. After enough trading days accumulate (a few months),
`data_cache/iv_history.csv` can be used to compute a real IV percentile
instead of the realized-vol proxy -- that swap is a future change, not
done here. This module only collects the data.
"""
from __future__ import annotations

import csv
import datetime as dt
import os

import pandas as pd

from src import data as data_mod
from src.config import Config

FIELDNAMES = ["date", "ticker", "underlying_price", "expiration", "dte", "atm_iv"]


def _nearest_iv(chain_df: pd.DataFrame, underlying_price: float) -> float | None:
    if chain_df is None or chain_df.empty:
        return None
    idx = (chain_df["strike"] - underlying_price).abs().idxmin()
    iv = chain_df.loc[idx, "impliedVolatility"]
    if iv is None or iv != iv or iv <= 0:  # NaN check via iv != iv
        return None
    return float(iv)


def _atm_iv(calls: pd.DataFrame, puts: pd.DataFrame, underlying_price: float) -> float | None:
    ivs = [v for v in (_nearest_iv(calls, underlying_price), _nearest_iv(puts, underlying_price)) if v is not None]
    return sum(ivs) / len(ivs) if ivs else None


def _iv_history_path(cfg: Config) -> str:
    return os.path.join(cfg.data.cache_dir, "iv_history.csv")


def _snapshot_ticker(ticker: str, cfg: Config) -> dict | None:
    price = data_mod.get_current_price(ticker)
    if price is None:
        return None

    expirations = data_mod.expirations_in_dte_window(ticker, cfg.strategy.min_dte, cfg.strategy.max_dte)
    if not expirations:
        return None

    target_dte = (cfg.strategy.min_dte + cfg.strategy.max_dte) / 2
    best_exp, best_snap, best_dist = None, None, None
    for exp in expirations:
        snap = data_mod.get_option_chain(ticker, exp, underlying_price=price)
        if snap is None:
            continue
        dist = abs(snap.dte - target_dte)
        if best_dist is None or dist < best_dist:
            best_exp, best_snap, best_dist = exp, snap, dist

    if best_snap is None:
        return None

    atm_iv = _atm_iv(best_snap.calls, best_snap.puts, price)
    if atm_iv is None:
        return None

    return {
        "date": dt.date.today().isoformat(),
        "ticker": ticker,
        "underlying_price": round(price, 2),
        "expiration": best_exp,
        "dte": best_snap.dte,
        "atm_iv": round(atm_iv, 4),
    }


def log_daily_snapshot(cfg: Config) -> str:
    """Best-effort: a failure on any one ticker is skipped, never raised,
    so this never breaks the scan/daily run that calls it."""
    path = _iv_history_path(cfg)
    rows = []
    for ticker in cfg.watchlist:
        try:
            row = _snapshot_ticker(ticker, cfg)
        except Exception:
            row = None
        if row is not None:
            rows.append(row)

    if rows:
        is_new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if is_new:
                writer.writeheader()
            writer.writerows(rows)

    return path


def load_iv_history(cfg: Config) -> pd.DataFrame:
    path = _iv_history_path(cfg)
    if not os.path.exists(path):
        return pd.DataFrame(columns=FIELDNAMES)
    return pd.read_csv(path)
