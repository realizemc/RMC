"""Ties the scan and (optionally) position checks together into one run,
suitable for a scheduled/automated daily job that also emails the result.

This is the single entrypoint a cron job / scheduled agent run should call
(`python main.py daily`) instead of composing `scan` and `positions check`
separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src import alerts
from src import equity_history
from src import html_report
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
    scorecard: object
    hot_rows: list | None
    hot_error: str | None
    csv_path: str
    scan_path: str
    md_path: str | None
    subject: str
    body: str
    html_body: str
    email_attempted: bool = False
    email_sent: bool = False
    email_error: str | None = None


def run_daily(cfg: Config, verbose: bool = False) -> DailyResult:
    results, reasons = run_screen(cfg, verbose=verbose)
    csv_path = alerts.append_csv_log(results, cfg)
    scan_path = alerts.save_last_scan(results, cfg)
    iv_history.log_daily_snapshot(cfg)
    equity_history.log_daily_snapshot(cfg)

    position_checks = []
    if cfg.notifications.include_position_checks:
        position_checks = positions_mod.check_all_open(cfg)

    md_path = (
        alerts.write_markdown_report(results, reasons, cfg, position_checks=position_checks)
        if cfg.alerts.write_markdown else None
    )

    sc = scorecard_mod.compute_scorecard(cfg)

    hot_rows, hot_error = None, None
    if cfg.notifications.include_hot_list:
        try:
            hot_rows = most_active_mod.get_top_active(cfg)
        except Exception as e:
            hot_error = str(e)

    # --- plain-text body (always sent as the fallback part) ---
    body_parts = ["=== NEW TRADE IDEAS ===", alerts.format_console(results, cfg)]
    if cfg.notifications.include_position_checks:
        body_parts += ["", "=== OPEN POSITION CHECKS ===", alerts.format_position_checks(position_checks)]
    if sc.total_closed:
        body_parts += [
            "", "=== TRACK RECORD ===",
            scorecard_mod.summarize(sc, starting_capital=cfg.account.portfolio_value),
        ]
    if cfg.notifications.include_hot_list:
        hot_text = f"(activity check failed, skipping: {hot_error})" if hot_error else most_active_mod.format_console(hot_rows)
        body_parts += ["", "=== TODAY'S OPTIONS ACTIVITY ===", hot_text]
    body = "\n".join(body_parts)

    # --- HTML dashboard body ---
    # Rendering is presentation only -- never let it block the plain-text
    # email (which already has everything) from going out.
    try:
        equity_df = equity_history.load_equity_history(cfg)
        html_body = html_report.render_html(
            cfg, results, position_checks, sc, hot_rows, hot_error, equity_df,
        )
    except Exception as e:
        html_body = f"<pre>HTML dashboard rendering failed ({e}); see plain-text version below.</pre>"

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
        scorecard=sc, hot_rows=hot_rows, hot_error=hot_error,
        csv_path=csv_path, scan_path=scan_path, md_path=md_path,
        subject=subject, body=body, html_body=html_body,
    )

    has_content = bool(results) or bool(position_checks)
    should_send = cfg.notifications.enabled and (has_content or cfg.notifications.send_on_empty)

    if should_send:
        daily.email_attempted = True
        try:
            send_email(daily.subject, daily.body, cfg.notifications.to_email, html_body=daily.html_body)
            daily.email_sent = True
        except NotifierError as e:
            daily.email_error = str(e)

    return daily
