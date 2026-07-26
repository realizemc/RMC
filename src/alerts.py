"""Turns screener output into things a human can actually read and act on:
console text, a markdown daily report, a CSV log, and a JSON snapshot that
`positions.py` uses so you can say "I took idea #2" without retyping strikes.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os

from src.config import Config
from src.screener import ScreenResult


def _leg_dict(leg) -> dict:
    if leg is None:
        return None
    return {
        "strike": leg.strike,
        "bid": leg.bid,
        "ask": leg.ask,
        "mid": leg.mid,
        "delta": leg.delta,
        "iv": leg.iv,
        "open_interest": leg.open_interest,
        "volume": leg.volume,
        "contract_symbol": leg.contract_symbol,
    }


def _result_to_dict(r: ScreenResult) -> dict:
    idea = r.idea
    return {
        "ticker": idea.ticker,
        "direction": idea.direction,
        "structure": idea.structure,
        "expiration": idea.expiration,
        "dte": idea.dte,
        "underlying_price": idea.underlying_price,
        "long_leg": _leg_dict(idea.long_leg),
        "short_leg": _leg_dict(idea.short_leg),
        "cost_per_contract": idea.cost_per_contract,
        "max_loss_per_contract": idea.max_loss_per_contract,
        "max_profit_per_contract": idea.max_profit_per_contract,
        "breakeven": idea.breakeven,
        "iv_rank_proxy": idea.iv_rank_proxy,
        "rsi": idea.rsi,
        "rationale": idea.rationale,
        "contracts": r.sizing.contracts,
        "total_cost": r.sizing.total_cost,
        "pct_of_portfolio": r.sizing.pct_of_portfolio,
    }


def format_console(results: list[ScreenResult], cfg: Config) -> str:
    if not results:
        return (
            "No trade ideas cleared every filter today (trend + RSI + volatility "
            "percentile + liquidity + budget). That's expected most days -- this "
            "system is deliberately picky so it doesn't force a bad trade to "
            "produce output."
        )

    lines = []
    for i, r in enumerate(results):
        idea = r.idea
        lines.append(f"\n{'=' * 60}")
        lines.append(f"IDEA #{i}: {idea.ticker}  ({idea.direction.upper()})")
        lines.append(f"{'=' * 60}")
        struct_label = idea.structure.replace("_", " ").title()
        lines.append(f"Structure : {struct_label}")
        lines.append(f"Expiration: {idea.expiration}  ({idea.dte} DTE)")
        lines.append(f"Underlying: ${idea.underlying_price:.2f}")

        opt_word = "Call" if "call" in idea.structure else "Put"
        lines.append(
            f"BUY  1x {idea.ticker} {idea.expiration} ${idea.long_leg.strike:.2f} {opt_word}"
            f"  @ ~${idea.long_leg.mid:.2f}  (delta {idea.long_leg.delta:+.2f}, "
            f"OI {idea.long_leg.open_interest}, IV {idea.long_leg.iv * 100:.0f}%)"
        )
        if idea.short_leg is not None:
            lines.append(
                f"SELL 1x {idea.ticker} {idea.expiration} ${idea.short_leg.strike:.2f} {opt_word}"
                f"  @ ~${idea.short_leg.mid:.2f}  (delta {idea.short_leg.delta:+.2f}, "
                f"OI {idea.short_leg.open_interest}, IV {idea.short_leg.iv * 100:.0f}%)"
            )

        lines.append(f"Net cost / contract : ${idea.cost_per_contract:.2f}")
        lines.append(f"Suggested contracts : {r.sizing.contracts}  "
                      f"(total ${r.sizing.total_cost:.2f}, {r.sizing.pct_of_portfolio * 100:.0f}% of portfolio)")
        lines.append(f"Max loss / contract : ${idea.max_loss_per_contract:.2f}")
        if idea.max_profit_per_contract is not None:
            lines.append(f"Max profit / contract: ${idea.max_profit_per_contract:.2f} (capped, debit spread)")
        else:
            lines.append("Max profit / contract: uncapped (long option) -- theoretical, real gains taper via theta/vega")
        lines.append(f"Breakeven at expiry  : ${idea.breakeven:.2f}")
        lines.append(f"Setup confidence     : {idea.confidence * 100:.0f}% (scales position size, not a win-probability)")
        lines.append(f"Why: {idea.rationale}")
        lines.append(
            f"Plan: take profit around +{cfg.exits.profit_target_pct * 100:.0f}% of premium, cut losses around "
            f"-{cfg.exits.stop_loss_pct * 100:.0f}%, or close by {idea.dte - cfg.exits.close_by_dte} DTE if neither hits first."
        )

    lines.append(f"\n{'=' * 60}")
    lines.append(
        "Reminder: this is alert output only. Nothing was sent to any broker. "
        "Verify live bid/ask in Robinhood before entering -- these prices are "
        "delayed quotes, not a live order book."
    )
    return "\n".join(lines)


def format_position_checks(checks: list[dict]) -> str:
    if not checks:
        return "No open tracked positions."

    lines = []
    for c in checks:
        p = c["position"]
        lines.append(f"\n[{p.id}] {p.contracts}x {p.ticker} {p.structure} {p.expiration}")
        if "error" in c:
            lines.append(f"  ERROR: {c['error']}")
            continue
        lines.append(f"  DTE remaining : {c['dte_remaining']}")
        lines.append(
            f"  Current value/contract: ${c['current_value_per_contract']:.2f} "
            f"(entry ${p.entry_cost_per_contract:.2f})"
        )
        lines.append(f"  P/L: {c['pnl_pct'] * 100:+.1f}% (${c['pnl_dollars']:+.2f} total)")
        for action in c["actions"]:
            lines.append(f"  -> {action}")
    return "\n".join(lines)


def write_markdown_report(results: list[ScreenResult], reasons: dict, cfg: Config) -> str:
    today = dt.date.today().isoformat()
    path = os.path.join(cfg.alerts.log_dir, f"report_{today}.md")

    lines = [f"# Options alert report -- {today}", ""]
    lines.append(f"Portfolio value: ${cfg.account.portfolio_value:.2f}  |  "
                  f"Max risk/trade: {cfg.account.max_risk_per_trade_pct * 100:.0f}%  |  "
                  f"Max open positions: {cfg.account.max_open_positions}")
    lines.append("")

    if not results:
        lines.append("No ideas cleared filters today.")
    else:
        for i, r in enumerate(results):
            idea = r.idea
            lines.append(f"## Idea #{i}: {idea.ticker} ({idea.direction}, {idea.structure})")
            lines.append(f"- Expiration: {idea.expiration} ({idea.dte} DTE)")
            lines.append(f"- Long leg: ${idea.long_leg.strike:.2f} @ ~${idea.long_leg.mid:.2f} (delta {idea.long_leg.delta:+.2f})")
            if idea.short_leg:
                lines.append(f"- Short leg: ${idea.short_leg.strike:.2f} @ ~${idea.short_leg.mid:.2f} (delta {idea.short_leg.delta:+.2f})")
            lines.append(f"- Cost/contract: ${idea.cost_per_contract:.2f}  |  Suggested contracts: {r.sizing.contracts}")
            lines.append(f"- Max loss: ${idea.max_loss_per_contract:.2f}  |  Breakeven: ${idea.breakeven:.2f}")
            lines.append(f"- Rationale: {idea.rationale}")
            lines.append("")

    lines.append("## Skipped tickers")
    for ticker, reason in reasons.items():
        if reason != "ok":
            lines.append(f"- **{ticker}**: {reason}")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def append_csv_log(results: list[ScreenResult], cfg: Config) -> str:
    path = os.path.join(cfg.alerts.log_dir, "alerts_log.csv")
    is_new = not os.path.exists(path)
    fieldnames = [
        "timestamp", "ticker", "direction", "structure", "expiration", "dte",
        "underlying_price", "long_strike", "short_strike", "cost_per_contract",
        "contracts", "total_cost", "max_loss_per_contract", "max_profit_per_contract",
        "breakeven", "iv_rank_proxy", "rsi",
    ]
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        now = dt.datetime.now().isoformat(timespec="seconds")
        for r in results:
            idea = r.idea
            writer.writerow({
                "timestamp": now,
                "ticker": idea.ticker,
                "direction": idea.direction,
                "structure": idea.structure,
                "expiration": idea.expiration,
                "dte": idea.dte,
                "underlying_price": f"{idea.underlying_price:.2f}",
                "long_strike": idea.long_leg.strike,
                "short_strike": idea.short_leg.strike if idea.short_leg else "",
                "cost_per_contract": f"{idea.cost_per_contract:.2f}",
                "contracts": r.sizing.contracts,
                "total_cost": f"{r.sizing.total_cost:.2f}",
                "max_loss_per_contract": f"{idea.max_loss_per_contract:.2f}",
                "max_profit_per_contract": (
                    f"{idea.max_profit_per_contract:.2f}" if idea.max_profit_per_contract is not None else ""
                ),
                "breakeven": f"{idea.breakeven:.2f}",
                "iv_rank_proxy": f"{idea.iv_rank_proxy:.0f}",
                "rsi": f"{idea.rsi:.0f}",
            })
    return path


def save_last_scan(results: list[ScreenResult], cfg: Config) -> str:
    path = os.path.join(cfg.alerts.log_dir, "last_scan.json")
    payload = {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "ideas": [_result_to_dict(r) for r in results],
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def load_last_scan(cfg: Config) -> dict | None:
    path = os.path.join(cfg.alerts.log_dir, "last_scan.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)
