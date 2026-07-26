"""Rolls up closed positions into a realized track record.

Only positions with a recorded exit value count -- a position closed
without ever being priced (e.g. the chain couldn't be fetched and no
manual fill price was given) is counted as closed but excluded from the
P/L stats rather than silently treated as a zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.config import Config
from src.positions import Position, load_positions


@dataclass
class Scorecard:
    total_closed: int = 0
    priced_closed: int = 0
    wins: int = 0
    total_realized_pnl: float = 0.0
    avg_pnl_pct: float = 0.0
    trades: list = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.priced_closed if self.priced_closed else 0.0


def compute_scorecard(cfg: Config) -> Scorecard:
    positions = load_positions(cfg)
    closed = [p for p in positions if p.status == "closed"]
    priced = [p for p in closed if p.realized_pnl_dollars is not None]
    wins = [p for p in priced if p.realized_pnl_dollars > 0]

    avg_pnl_pct = (
        sum(p.realized_pnl_pct for p in priced if p.realized_pnl_pct is not None) / len(priced)
        if priced else 0.0
    )

    return Scorecard(
        total_closed=len(closed),
        priced_closed=len(priced),
        wins=len(wins),
        total_realized_pnl=sum(p.realized_pnl_dollars for p in priced),
        avg_pnl_pct=avg_pnl_pct,
        trades=priced,
    )


def summarize(sc: Scorecard, starting_capital: float | None = None) -> str:
    if sc.total_closed == 0:
        return "No closed positions yet -- nothing to score."

    lines = [
        f"Closed positions : {sc.total_closed} ({sc.priced_closed} with recorded exit price)",
        f"Win rate         : {sc.win_rate * 100:.0f}%",
        f"Total realized P/L: ${sc.total_realized_pnl:+.2f}",
        f"Avg trade return : {sc.avg_pnl_pct * 100:+.1f}%",
    ]
    if starting_capital:
        lines.append(
            f"Rough equity     : ${starting_capital:.2f} -> ${starting_capital + sc.total_realized_pnl:.2f} "
            f"(realized P/L only -- ignores any still-open positions)"
        )
    unpriced = sc.total_closed - sc.priced_closed
    if unpriced:
        lines.append(f"Note: {unpriced} closed position(s) have no recorded exit price and are excluded above.")
    return "\n".join(lines)
