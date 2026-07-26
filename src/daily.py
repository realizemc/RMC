"""Ties the scan and (optionally) position checks together into one run,
suitable for a scheduled/automated daily job that also emails the result.

This is the single entrypoint a cron job / scheduled agent run should call
(`python main.py daily`) instead of composing `scan` and `positions check`
separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src import alerts
from src import iv_history
from src import most_active as most_active_mod
from src import positions as positions_mod
from src import scorecard as scorecard_mod
from src.config import Config
from src.notifier import NotifierError, send_email
from src.screener import run_screen


@dataclass
class DailyResult:
    results: list
    reasons: dict
    position_checks: list
    csv_path: str
    scan_path: str
    md_path: str | None
    subject: str
    body: str
    email_attempted: bool = False
    email_sent: bool = False
    email_error: str | None = None


def run_daily(cfg: Config, verbose: bool = False) -> DailyResult:
    results, reasons = run_screen(cfg, verbose=verbose)
    csv_path = alerts.append_csv_log(results, cfg)
    scan_path = alerts.save_last_scan(results, cfg)
    md_path = alerts.write_markdown_report(results, reasons, cfg) if cfg.alerts.write_markdown else None
    iv_history.log_daily_snapshot(cfg)

    position_checks = []
    if cfg.notifications.include_position_checks:
        position_checks = positions_mod.check_all_open(cfg)

    body_parts = ["=== NEW TRADE IDEAS ===", alerts.format_console(results)]
    if cfg.notifications.include_position_checks:
        body_parts += ["", "=== OPEN POSITION CHECKS ===", alerts.format_position_checks(position_checks)]

    sc = scorecard_mod.compute_scorecard(cfg)
    if sc.total_closed:
        body_parts += [
            "", "=== TRACK RECORD ===",
            scorecard_mod.summarize(sc, starting_capital=cfg.account.portfolio_value),
        ]

    if cfg.notifications.include_hot_list:
        try:
            hot_rows = most_active_mod.get_top_active(cfg)
            hot_text = most_active_mod.format_console(hot_rows)
        except Exception as e:
            hot_text = f"(activity check failed, skipping: {e})"
        body_parts += ["", "=== TODAY'S OPTIONS ACTIVITY ===", hot_text]

    body = "\n".join(body_parts)

    if results:
        subject = f"Options scan -- {len(results)} idea(s) found"
    else:
        subject = "Options scan -- no new ideas"
    if position_checks:
        actionable = [c for c in position_checks if c.get("actions", ["HOLD"]) != ["HOLD -- no exit rule triggered"]]
        if actionable:
            subject += f" | {len(actionable)} position(s) need attention"

    daily = DailyResult(
        results=results, reasons=reasons, position_checks=position_checks,
        csv_path=csv_path, scan_path=scan_path, md_path=md_path,
        subject=subject, body=body,
    )

    has_content = bool(results) or bool(position_checks)
    should_send = cfg.notifications.enabled and (has_content or cfg.notifications.send_on_empty)

    if should_send:
        daily.email_attempted = True
        try:
            send_email(daily.subject, daily.body, cfg.notifications.to_email)
            daily.email_sent = True
        except NotifierError as e:
            daily.email_error = str(e)

    return daily
