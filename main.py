#!/usr/bin/env python3
"""CLI for the options alert system.

  python main.py scan                 -- run today's screen, print + log ideas
  python main.py backtest              -- backtest the strategy's signal logic
  python main.py positions add IDX     -- start tracking idea #IDX from the last scan
  python main.py positions list        -- show tracked positions
  python main.py positions check       -- get hold/close guidance on open positions
  python main.py positions close ID    -- mark a position closed (records realized P/L)
  python main.py positions scorecard   -- realized P/L summary across all closed positions
  python main.py hot                   -- rank a curated universe by today's options activity

This system NEVER places, modifies, or cancels a real order. It reads
market data and tells you what it thinks. You pull the trigger in Robinhood.
"""
from __future__ import annotations

import argparse
import sys

from src import alerts, backtest as backtest_mod, iv_history, positions as positions_mod
from src import most_active as most_active_mod
from src import scorecard as scorecard_mod
from src.config import load_config
from src.daily import run_daily
from src.screener import run_screen

DISCLAIMER = (
    "Options trading involves substantial risk and is not suitable for all\n"
    "investors. This tool provides no guarantee of profit; past and\n"
    "backtested performance does not predict future results. This is not\n"
    "financial advice. Nothing in this system places real trades -- it is\n"
    "decision support only.\n"
)


def cmd_scan(args):
    cfg = load_config(args.config)
    ad_hoc = bool(args.tickers)
    if ad_hoc:
        cfg.watchlist = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    print(DISCLAIMER)
    print(f"Scanning {len(cfg.watchlist)} tickers "
          f"(portfolio ${cfg.account.portfolio_value:.2f}, "
          f"max risk/trade {cfg.account.max_risk_per_trade_pct * 100:.0f}%)...\n")

    results, reasons = run_screen(cfg, verbose=args.verbose)

    print(alerts.format_console(results, cfg))

    csv_path = alerts.append_csv_log(results, cfg)
    scan_path = alerts.save_last_scan(results, cfg)
    print(f"\nLogged to {csv_path}")
    print(f"Saved scan snapshot to {scan_path} (use `positions add <N>` to track an idea)")

    if cfg.alerts.write_markdown:
        md_path = alerts.write_markdown_report(results, reasons, cfg)
        print(f"Markdown report: {md_path}")

    if not ad_hoc:
        # Only build IV history off the real, persistent watchlist -- not
        # one-off `--tickers` checks.
        iv_history.log_daily_snapshot(cfg)


def cmd_hot(args):
    cfg = load_config(args.config)
    top_n = args.top or cfg.most_active.top_n
    print(f"Checking options activity across {len(cfg.most_active.universe)} liquid names "
          f"(this can take a minute)...\n")
    rows = most_active_mod.get_top_active(cfg, top_n=top_n)
    print(most_active_mod.format_console(rows))


def cmd_daily(args):
    cfg = load_config(args.config)
    print(DISCLAIMER)
    result = run_daily(cfg, verbose=args.verbose)
    print(result.body)
    print(f"\nLogged to {result.csv_path}")
    print(f"Saved scan snapshot to {result.scan_path}")
    if result.md_path:
        print(f"Markdown report: {result.md_path}")

    if not result.email_attempted:
        print("\nEmail not sent (nothing to report and send_on_empty is false).")
    elif result.email_sent:
        print(f"\nEmailed report to {cfg.notifications.to_email}")
    else:
        print(f"\nEmail NOT sent: {result.email_error}")


def cmd_backtest(args):
    cfg = load_config(args.config)
    tickers = args.tickers.split(",") if args.tickers else None
    print(DISCLAIMER)
    print(f"Backtesting {tickers or cfg.watchlist} over {args.years} years "
          f"(modeled option pricing -- see src/backtest.py docstring for caveats)...\n")
    result = backtest_mod.run_backtest(cfg, tickers=tickers, years=args.years, vol_multiplier=args.vol_multiplier)
    print(backtest_mod.summarize(result))


def cmd_positions_add(args):
    cfg = load_config(args.config)
    scan = alerts.load_last_scan(cfg)
    if scan is None:
        print("No saved scan found. Run `python main.py scan` first.")
        sys.exit(1)
    if args.idx < 0 or args.idx >= len(scan["ideas"]):
        print(f"Idea index {args.idx} out of range (last scan had {len(scan['ideas'])} ideas).")
        sys.exit(1)
    pos = positions_mod.add_position_from_scan(cfg, scan, args.idx, contracts=args.contracts)
    print(f"Tracking position {pos.id}: {pos.contracts}x {pos.ticker} {pos.structure} "
          f"{pos.expiration} (entry cost/contract ${pos.entry_cost_per_contract:.2f})")
    print("Only run this AFTER you've actually placed the trade in Robinhood.")


def cmd_positions_list(args):
    cfg = load_config(args.config)
    pos_list = positions_mod.load_positions(cfg)
    if not pos_list:
        print("No tracked positions.")
        return
    for p in pos_list:
        line = (f"[{p.id}] {p.status:6s} {p.contracts}x {p.ticker} {p.structure} "
                f"{p.expiration} strike(s) {p.long_strike}/{p.short_strike or '-'} "
                f"entry ${p.entry_cost_per_contract:.2f} opened {p.entry_date}")
        if p.status == "closed" and p.realized_pnl_dollars is not None:
            line += f" | closed {p.close_date} P/L ${p.realized_pnl_dollars:+.2f} ({p.exit_source})"
        print(line)


def cmd_positions_check(args):
    cfg = load_config(args.config)
    checks = positions_mod.check_all_open(cfg)
    if not checks:
        print("No open positions to check.")
        return
    for c in checks:
        p = c["position"]
        print(f"\n[{p.id}] {p.contracts}x {p.ticker} {p.structure} {p.expiration}")
        if "error" in c:
            print(f"  ERROR: {c['error']}")
            continue
        print(f"  DTE remaining : {c['dte_remaining']}")
        print(f"  Current value/contract: ${c['current_value_per_contract']:.2f} "
              f"(entry ${p.entry_cost_per_contract:.2f})")
        print(f"  P/L: {c['pnl_pct'] * 100:+.1f}% (${c['pnl_dollars']:+.2f} total)")
        for action in c["actions"]:
            print(f"  -> {action}")


def cmd_positions_close(args):
    cfg = load_config(args.config)
    ok = positions_mod.close_position(
        cfg, args.id, note=args.note or "", fill_price_per_contract=args.fill_price,
    )
    if not ok:
        print(f"No open position found with id {args.id}")
        return
    pos = next(p for p in positions_mod.load_positions(cfg) if p.id == args.id)
    if pos.realized_pnl_dollars is not None:
        print(f"Closed. Realized P/L: ${pos.realized_pnl_dollars:+.2f} "
              f"({pos.realized_pnl_pct * 100:+.1f}%, priced via {pos.exit_source})")
    else:
        print("Closed. No exit price recorded (chain unavailable and no --fill-price given), "
              "so this trade won't count toward the scorecard.")


def cmd_positions_scorecard(args):
    cfg = load_config(args.config)
    sc = scorecard_mod.compute_scorecard(cfg)
    print(scorecard_mod.summarize(sc, starting_capital=cfg.account.portfolio_value))


def build_parser():
    p = argparse.ArgumentParser(description="Options trade-idea alert system (alerts only, no order placement).")
    p.add_argument("--config", default=None, help="Path to config.yaml (default: repo config.yaml)")
    sub = p.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Run today's screen and print/log trade ideas")
    p_scan.add_argument("--verbose", action="store_true", help="Print skip reasons for every ticker")
    p_scan.add_argument("--tickers", default=None,
                         help="Comma-separated one-off override of the watchlist (doesn't touch config.yaml or IV history)")
    p_scan.set_defaults(func=cmd_scan)

    p_hot = sub.add_parser("hot", help="Rank a curated universe by today's near-term options activity")
    p_hot.add_argument("--top", type=int, default=None, help="Override most_active.top_n from config.yaml")
    p_hot.set_defaults(func=cmd_hot)

    p_daily = sub.add_parser("daily", help="Run scan + position checks and email the combined report")
    p_daily.add_argument("--verbose", action="store_true", help="Print skip reasons for every ticker")
    p_daily.set_defaults(func=cmd_daily)

    p_bt = sub.add_parser("backtest", help="Backtest the strategy's signal logic")
    p_bt.add_argument("--years", type=int, default=3)
    p_bt.add_argument("--tickers", default=None, help="Comma-separated override of the watchlist")
    p_bt.add_argument("--vol-multiplier", dest="vol_multiplier", type=float, default=1.15,
                       help="Modeled IV = realized vol * this multiplier (IV usually trades above realized vol)")
    p_bt.set_defaults(func=cmd_backtest)

    p_pos = sub.add_parser("positions", help="Track/check trades you manually placed")
    pos_sub = p_pos.add_subparsers(dest="positions_command", required=True)

    p_pos_add = pos_sub.add_parser("add", help="Start tracking an idea from the last scan")
    p_pos_add.add_argument("idx", type=int, help="Idea index from the last `scan` run")
    p_pos_add.add_argument("--contracts", type=int, default=None, help="Override suggested contract count")
    p_pos_add.set_defaults(func=cmd_positions_add)

    p_pos_list = pos_sub.add_parser("list", help="List tracked positions")
    p_pos_list.set_defaults(func=cmd_positions_list)

    p_pos_check = pos_sub.add_parser("check", help="Check exit rules against current prices")
    p_pos_check.set_defaults(func=cmd_positions_check)

    p_pos_close = pos_sub.add_parser("close", help="Mark a tracked position closed")
    p_pos_close.add_argument("id", type=str)
    p_pos_close.add_argument("--note", type=str, default=None)
    p_pos_close.add_argument(
        "--fill-price", dest="fill_price", type=float, default=None,
        help="What you actually got filled at in Robinhood, total $ per contract "
             "(e.g. 82.00 for a $0.82 premium). Omit to use this system's live model "
             "price as an estimate.",
    )
    p_pos_close.set_defaults(func=cmd_positions_close)

    p_pos_scorecard = pos_sub.add_parser("scorecard", help="Realized P/L summary across all closed positions")
    p_pos_scorecard.set_defaults(func=cmd_positions_scorecard)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.config is None:
        from src.config import DEFAULT_CONFIG_PATH
        args.config = DEFAULT_CONFIG_PATH
    args.func(args)


if __name__ == "__main__":
    main()
