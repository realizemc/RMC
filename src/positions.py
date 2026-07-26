"""Tracks trades YOU actually placed (manually, in Robinhood) so the system
can tell you when to close them. This system never places or cancels
orders -- it only tells you what it thinks you should do.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from dataclasses import asdict, dataclass
from typing import Optional

from src.config import Config
from src.data import get_option_chain


@dataclass
class Position:
    id: str
    ticker: str
    structure: str
    expiration: str
    long_strike: float
    short_strike: Optional[float]
    long_contract_symbol: str
    short_contract_symbol: Optional[str]
    entry_cost_per_contract: float
    contracts: int
    entry_date: str
    status: str = "open"       # 'open' | 'closed'
    close_date: Optional[str] = None
    close_note: Optional[str] = None


def _positions_path(cfg: Config) -> str:
    return os.path.join(cfg.alerts.log_dir, "positions.json")


def load_positions(cfg: Config) -> list[Position]:
    path = _positions_path(cfg)
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        raw = json.load(f)
    return [Position(**p) for p in raw]


def save_positions(cfg: Config, positions: list[Position]) -> None:
    path = _positions_path(cfg)
    with open(path, "w") as f:
        json.dump([asdict(p) for p in positions], f, indent=2)


def add_position_from_scan(cfg: Config, scan: dict, idea_index: int, contracts: Optional[int] = None) -> Position:
    idea = scan["ideas"][idea_index]
    long_leg = idea["long_leg"]
    short_leg = idea["short_leg"]

    pos = Position(
        id=str(uuid.uuid4())[:8],
        ticker=idea["ticker"],
        structure=idea["structure"],
        expiration=idea["expiration"],
        long_strike=long_leg["strike"],
        short_strike=short_leg["strike"] if short_leg else None,
        long_contract_symbol=long_leg["contract_symbol"],
        short_contract_symbol=short_leg["contract_symbol"] if short_leg else None,
        entry_cost_per_contract=idea["cost_per_contract"],
        contracts=contracts if contracts is not None else idea["contracts"],
        entry_date=dt.date.today().isoformat(),
    )

    positions = load_positions(cfg)
    positions.append(pos)
    save_positions(cfg, positions)
    return pos


def close_position(cfg: Config, position_id: str, note: str = "") -> bool:
    positions = load_positions(cfg)
    for p in positions:
        if p.id == position_id:
            p.status = "closed"
            p.close_date = dt.date.today().isoformat()
            p.close_note = note
            save_positions(cfg, positions)
            return True
    return False


def _find_contract_row(chain_df, contract_symbol: str):
    matches = chain_df[chain_df["contractSymbol"] == contract_symbol]
    if matches.empty:
        return None
    return matches.iloc[0]


def check_position(cfg: Config, pos: Position) -> dict:
    """Re-prices one open position against the live chain and applies the
    exit rules from config. Returns a dict describing current state and any
    recommended action."""
    exp_date = dt.datetime.strptime(pos.expiration, "%Y-%m-%d").date()
    dte_remaining = (exp_date - dt.date.today()).days

    if dte_remaining < 0:
        return {"position": pos, "error": "expiration already passed -- check if it was exercised/expired"}

    snap = get_option_chain(pos.ticker, pos.expiration)
    if snap is None:
        return {"position": pos, "error": "could not load current chain (market closed / bad ticker / expired)"}

    is_call = "call" in pos.structure
    df = snap.calls if is_call else snap.puts

    long_row = _find_contract_row(df, pos.long_contract_symbol)
    if long_row is None:
        return {"position": pos, "error": "long contract symbol no longer found in chain"}
    long_mid = (float(long_row["bid"]) + float(long_row["ask"])) / 2

    current_value = long_mid
    if pos.short_contract_symbol:
        short_row = _find_contract_row(df, pos.short_contract_symbol)
        if short_row is None:
            return {"position": pos, "error": "short contract symbol no longer found in chain"}
        short_mid = (float(short_row["bid"]) + float(short_row["ask"])) / 2
        current_value = long_mid - short_mid

    current_value_per_contract = current_value * 100
    pnl_pct = (current_value_per_contract - pos.entry_cost_per_contract) / pos.entry_cost_per_contract
    pnl_dollars = (current_value_per_contract - pos.entry_cost_per_contract) * pos.contracts

    actions = []
    if pnl_pct >= cfg.exits.profit_target_pct:
        actions.append(f"PROFIT TARGET HIT (+{pnl_pct * 100:.0f}%) -- consider closing")
    if pnl_pct <= -cfg.exits.stop_loss_pct:
        actions.append(f"STOP LOSS HIT ({pnl_pct * 100:.0f}%) -- consider cutting losses")
    if dte_remaining <= cfg.exits.close_by_dte:
        actions.append(f"ONLY {dte_remaining} DTE LEFT -- theta decay accelerating, consider closing regardless of P/L")

    return {
        "position": pos,
        "dte_remaining": dte_remaining,
        "current_value_per_contract": current_value_per_contract,
        "pnl_pct": pnl_pct,
        "pnl_dollars": pnl_dollars,
        "actions": actions or ["HOLD -- no exit rule triggered"],
    }


def check_all_open(cfg: Config) -> list[dict]:
    positions = load_positions(cfg)
    return [check_position(cfg, p) for p in positions if p.status == "open"]
