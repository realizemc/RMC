"""Ranks a curated universe of liquid names by today's near-term options
activity, as a discovery tool separate from the trading `watchlist`.

Honesty about what this actually is: there's no free, reliable feed for
"the whole market's most active options today" (that's normally a paid
feed -- Barchart, MarketChameleon, CBOE all gate it). This instead sums
call+put volume at the NEAREST expiration only, for a hand-picked list of
liquid names in config.yaml's `most_active.universe`. That's a proxy for
"how actively is this name being optioned right now," not a literal
whole-market ranking, and it ignores volume at further-out expirations.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from src import data as data_mod
from src.config import Config


@dataclass
class ActivityRow:
    ticker: str
    price: float
    expiration: str
    dte: int
    call_volume: int
    put_volume: int
    total_volume: int
    open_interest: int
    put_call_ratio: Optional[float]


def _snapshot_ticker(ticker: str) -> Optional[ActivityRow]:
    price = data_mod.get_current_price(ticker)
    if price is None:
        return None

    expirations = data_mod.list_expirations(ticker)
    if not expirations:
        return None

    snap = data_mod.get_option_chain(ticker, expirations[0], underlying_price=price)
    if snap is None:
        return None

    call_volume = int(snap.calls["volume"].fillna(0).sum()) if not snap.calls.empty else 0
    put_volume = int(snap.puts["volume"].fillna(0).sum()) if not snap.puts.empty else 0
    call_oi = int(snap.calls["openInterest"].fillna(0).sum()) if not snap.calls.empty else 0
    put_oi = int(snap.puts["openInterest"].fillna(0).sum()) if not snap.puts.empty else 0

    if call_volume == 0 and put_volume == 0:
        return None

    return ActivityRow(
        ticker=ticker,
        price=price,
        expiration=snap.expiration,
        dte=snap.dte,
        call_volume=call_volume,
        put_volume=put_volume,
        total_volume=call_volume + put_volume,
        open_interest=call_oi + put_oi,
        put_call_ratio=(put_volume / call_volume) if call_volume > 0 else None,
    )


def get_top_active(cfg: Config, top_n: int | None = None, max_workers: int = 10) -> list[ActivityRow]:
    top_n = top_n or cfg.most_active.top_n
    rows: list[ActivityRow] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_snapshot_ticker, t): t for t in cfg.most_active.universe}
        for future in as_completed(futures):
            try:
                row = future.result()
            except Exception:
                row = None
            if row is not None:
                rows.append(row)

    rows.sort(key=lambda r: r.total_volume, reverse=True)
    return rows[:top_n]


def format_console(rows: list[ActivityRow]) -> str:
    if not rows:
        return "No options activity data available right now (market closed, or all lookups failed)."

    lines = [
        "Most active options right now (near-term expiration only, proxy -- see module docstring):",
        "",
        f"{'#':<3}{'Ticker':<8}{'Price':>9}{'Volume':>12}{'OI':>10}{'P/C ratio':>11}  Expiration",
    ]
    for i, r in enumerate(rows, start=1):
        pc = f"{r.put_call_ratio:.2f}" if r.put_call_ratio is not None else "n/a"
        lines.append(
            f"{i:<3}{r.ticker:<8}{r.price:>9.2f}{r.total_volume:>12,}{r.open_interest:>10,}{pc:>11}  "
            f"{r.expiration} ({r.dte} DTE)"
        )
    lines.append("")
    lines.append(
        "This is a discovery list, not a trade idea. To check any of these against "
        "the actual strategy, run: python main.py scan --tickers TICKER1,TICKER2"
    )
    return "\n".join(lines)
