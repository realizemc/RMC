"""Logs a rough daily equity snapshot (starting capital + cumulative
realized P/L) so the HTML dashboard can draw a simple trend sparkline.

This is NOT mark-to-market account value -- it ignores unrealized P/L on
any currently open positions, the same simplification `scorecard.py`
already uses. One row per calendar date; re-running on the same day
updates that day's row instead of duplicating it.
"""
from __future__ import annotations

import csv
import datetime as dt
import os

import pandas as pd

from src import scorecard as scorecard_mod
from src.config import Config

FIELDNAMES = ["date", "equity"]


def _path(cfg: Config) -> str:
    return os.path.join(cfg.data.cache_dir, "equity_history.csv")


def log_daily_snapshot(cfg: Config) -> str:
    sc = scorecard_mod.compute_scorecard(cfg)
    equity = round(cfg.account.portfolio_value + sc.total_realized_pnl, 2)
    today = dt.date.today().isoformat()
    path = _path(cfg)

    rows = []
    if os.path.exists(path):
        with open(path, "r", newline="") as f:
            rows = list(csv.DictReader(f))
    rows = [r for r in rows if r["date"] != today]
    rows.append({"date": today, "equity": str(equity)})
    rows.sort(key=lambda r: r["date"])

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path


def load_equity_history(cfg: Config) -> pd.DataFrame:
    path = _path(cfg)
    if not os.path.exists(path):
        return pd.DataFrame(columns=FIELDNAMES)
    return pd.read_csv(path)
