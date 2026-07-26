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

from src import data as data_mod
from src.config import Config
from src.data import get_option_chain
from src.options_pricing import bs_theta, resolve_implied_vol


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
    exit_value_per_contract: Optional[float] = None
    exit_source: Optional[str] = None   # 'manual fill price' | 'live model estimate'
    realized_pnl_dollars: Optional[float] = None
    realized_pnl_pct: Optional[float] = None


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


VALID_STRUCTURES = {"long_call", "long_put", "call_debit_spread", "put_debit_spread"}


def _find_row_by_strike(chain_df, strike: float, tol: float = 0.005):
    matches = chain_df[(chain_df["strike"] - strike).abs() <= tol]
    if matches.empty:
        return None
    return matches.iloc[0]


def add_manual_position(
    cfg: Config,
    ticker: str,
    structure: str,
    expiration: str,
    long_strike: float,
    entry_cost_per_contract: float,
    contracts: int,
    short_strike: Optional[float] = None,
) -> tuple[Optional[Position], str]:
    """Tracks a trade the system didn't suggest -- something you found on
    `hot`, or a pick entirely of your own. Looks up the real contract(s) on
    the live chain (by ticker/expiration/strike) so later `positions check`
    calls can find and re-price them, exactly like a system-suggested idea.

    Returns (Position, "ok") on success, or (None, reason) on failure --
    never raises, so a typo'd strike/expiration just gets a clear message
    instead of a crash.
    """
    if structure not in VALID_STRUCTURES:
        return None, f"structure must be one of {sorted(VALID_STRUCTURES)}"

    is_spread = "spread" in structure
    if is_spread and short_strike is None:
        return None, f"{structure} requires a short_strike"
    if not is_spread and short_strike is not None:
        return None, f"{structure} doesn't take a short_strike (that's only for debit spreads)"

    option_type = "call" if "call" in structure else "put"

    snap = get_option_chain(ticker, expiration)
    if snap is None:
        return None, f"could not load an options chain for {ticker} {expiration} (bad ticker/expiration, or market data unavailable)"

    df = snap.calls if option_type == "call" else snap.puts
    long_row = _find_row_by_strike(df, long_strike)
    if long_row is None:
        return None, f"no {option_type} contract found at strike {long_strike} for {ticker} {expiration}"

    short_contract_symbol = None
    if is_spread:
        short_row = _find_row_by_strike(df, short_strike)
        if short_row is None:
            return None, f"no {option_type} contract found at short strike {short_strike} for {ticker} {expiration}"
        is_valid_spread = (
            (option_type == "call" and short_strike > long_strike)
            or (option_type == "put" and short_strike < long_strike)
        )
        if not is_valid_spread:
            return None, (
                f"invalid {structure}: short strike must be "
                f"{'above' if option_type == 'call' else 'below'} the long strike"
            )
        short_contract_symbol = str(short_row["contractSymbol"])

    pos = Position(
        id=str(uuid.uuid4())[:8],
        ticker=ticker.upper(),
        structure=structure,
        expiration=expiration,
        long_strike=long_strike,
        short_strike=short_strike,
        long_contract_symbol=str(long_row["contractSymbol"]),
        short_contract_symbol=short_contract_symbol,
        entry_cost_per_contract=entry_cost_per_contract,
        contracts=contracts,
        entry_date=dt.date.today().isoformat(),
    )

    positions = load_positions(cfg)
    positions.append(pos)
    save_positions(cfg, positions)
    return pos, "ok"


def close_position(
    cfg: Config,
    position_id: str,
    note: str = "",
    fill_price_per_contract: Optional[float] = None,
) -> bool:
    """Marks a position closed and records realized P/L.

    `fill_price_per_contract` should be what you actually got filled at in
    Robinhood (same units as entry_cost_per_contract: total $ per contract,
    e.g. 82.00 for a $0.82 premium). If omitted, falls back to this
    system's live model price as an estimate -- less accurate than a real
    fill, but better than no P/L data at all.
    """
    positions = load_positions(cfg)
    for p in positions:
        if p.id != position_id:
            continue

        exit_value, source = fill_price_per_contract, "manual fill price"
        if exit_value is None:
            check = check_position(cfg, p)
            if "error" not in check:
                exit_value = check["current_value_per_contract"]
                source = "live model estimate"

        if exit_value is not None:
            p.exit_value_per_contract = exit_value
            p.exit_source = source
            p.realized_pnl_dollars = (exit_value - p.entry_cost_per_contract) * p.contracts
            p.realized_pnl_pct = (
                (exit_value - p.entry_cost_per_contract) / p.entry_cost_per_contract
                if p.entry_cost_per_contract else None
            )

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

    option_type = "call" if is_call else "put"
    S = snap.underlying_price
    T = max(dte_remaining, 0) / 365.0
    r = data_mod.RISK_FREE_RATE

    long_row = _find_contract_row(df, pos.long_contract_symbol)
    if long_row is None:
        return {"position": pos, "error": "long contract symbol no longer found in chain"}
    long_mid = (float(long_row["bid"]) + float(long_row["ask"])) / 2
    long_iv = resolve_implied_vol(long_row.get("impliedVolatility"), long_mid, S, pos.long_strike, T, r, option_type)
    theta_per_share = bs_theta(S, pos.long_strike, T, r, long_iv, option_type) if long_iv else None

    current_value = long_mid
    if pos.short_contract_symbol:
        short_row = _find_contract_row(df, pos.short_contract_symbol)
        if short_row is None:
            return {"position": pos, "error": "short contract symbol no longer found in chain"}
        short_mid = (float(short_row["bid"]) + float(short_row["ask"])) / 2
        current_value = long_mid - short_mid
        short_iv = resolve_implied_vol(short_row.get("impliedVolatility"), short_mid, S, pos.short_strike, T, r, option_type)
        if theta_per_share is not None and short_iv is not None:
            # Short leg's decay works FOR you, so it offsets the long leg's.
            theta_per_share -= bs_theta(S, pos.short_strike, T, r, short_iv, option_type)

    current_value_per_contract = current_value * 100
    pnl_pct = (current_value_per_contract - pos.entry_cost_per_contract) / pos.entry_cost_per_contract
    pnl_dollars = (current_value_per_contract - pos.entry_cost_per_contract) * pos.contracts

    theta_per_contract = theta_per_share * 100 if theta_per_share is not None else None
    theta_pct_of_value = (
        abs(theta_per_contract) / current_value_per_contract
        if theta_per_contract is not None and current_value_per_contract > 0 else None
    )

    actions = []
    if pnl_pct >= cfg.exits.profit_target_pct:
        actions.append(f"PROFIT TARGET HIT (+{pnl_pct * 100:.0f}%) -- consider closing")
    if pnl_pct <= -cfg.exits.stop_loss_pct:
        actions.append(f"STOP LOSS HIT ({pnl_pct * 100:.0f}%) -- consider cutting losses")

    if cfg.exits.exit_rule_mode == "theta_pct":
        if theta_pct_of_value is not None and theta_pct_of_value >= cfg.exits.theta_pct_of_value:
            actions.append(
                f"THETA ACCELERATING (losing {theta_pct_of_value * 100:.1f}%/day of value) -- consider closing"
            )
    else:
        if dte_remaining <= cfg.exits.close_by_dte:
            actions.append(f"ONLY {dte_remaining} DTE LEFT -- theta decay accelerating, consider closing regardless of P/L")

    return {
        "position": pos,
        "dte_remaining": dte_remaining,
        "current_value_per_contract": current_value_per_contract,
        "pnl_pct": pnl_pct,
        "pnl_dollars": pnl_dollars,
        "theta_per_contract": theta_per_contract,
        "theta_pct_of_value": theta_pct_of_value,
        "actions": actions or ["HOLD -- no exit rule triggered"],
    }


def check_all_open(cfg: Config) -> list[dict]:
    positions = load_positions(cfg)
    return [check_position(cfg, p) for p in positions if p.status == "open"]
