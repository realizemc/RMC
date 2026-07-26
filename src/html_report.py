"""Renders the daily report as email-safe HTML (inline styles, table-based
layout, no JS/flexbox/grid) so it displays consistently in Gmail.

This mirrors exactly what `daily.run_daily` already computes -- it's a
visual presentation of the same data as the plain-text email, not a
second source of truth.
"""
from __future__ import annotations

import html as html_mod

import pandas as pd

from src.config import Config
from src.scorecard import Scorecard

FONT = "font-family:-apple-system,Helvetica,Arial,sans-serif;"
CARD_BORDER = "border:1px solid #e3e3e8;border-radius:8px;"
MUTED = "#6b6b76"


def _esc(v) -> str:
    return html_mod.escape(str(v))


def _badge(text: str, bg: str, fg: str) -> str:
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:12px;'
        f'background:{bg};color:{fg};font-size:11px;font-weight:700;letter-spacing:.02em;">{_esc(text)}</span>'
    )


def _section_title(text: str) -> str:
    return (
        f'<div style="{FONT}font-size:14px;font-weight:700;color:#1a1a2e;'
        f'margin:28px 0 12px;text-transform:uppercase;letter-spacing:.04em;">{_esc(text)}</div>'
    )


def _idea_card(result) -> str:
    idea = result.idea
    direction_badge = (
        _badge("BULLISH", "#e8f5e9", "#2e7d32") if idea.direction == "bullish"
        else _badge("BEARISH", "#ffebee", "#c62828")
    )
    opt_word = "Call" if "call" in idea.structure else "Put"
    struct_label = idea.structure.replace("_", " ").title()

    legs = (
        f'<div style="{FONT}font-size:13px;color:#1a1a1a;margin-top:8px;line-height:1.6;">'
        f'BUY 1x {_esc(idea.ticker)} {_esc(idea.expiration)} ${idea.long_leg.strike:.2f} {opt_word} '
        f'@ ~${idea.long_leg.mid:.2f} (delta {idea.long_leg.delta:+.2f})'
    )
    if idea.short_leg is not None:
        legs += (
            f'<br>SELL 1x {_esc(idea.ticker)} {_esc(idea.expiration)} ${idea.short_leg.strike:.2f} {opt_word} '
            f'@ ~${idea.short_leg.mid:.2f} (delta {idea.short_leg.delta:+.2f})'
        )
    legs += "</div>"

    max_profit = (
        f"${idea.max_profit_per_contract:.2f} (capped)" if idea.max_profit_per_contract is not None
        else "uncapped (long option)"
    )

    return f"""
    <div style="{CARD_BORDER}padding:16px;margin-bottom:12px;">
      <div style="{FONT}font-size:15px;font-weight:700;color:#1a1a2e;">
        {_esc(idea.ticker)} &nbsp; {direction_badge} &nbsp;
        <span style="color:{MUTED};font-weight:400;font-size:12px;">{_esc(struct_label)}</span>
      </div>
      {legs}
      <table role="presentation" width="100%" style="{FONT}font-size:12px;color:{MUTED};margin-top:10px;border-collapse:collapse;">
        <tr>
          <td style="padding:2px 0;">Cost/contract</td><td style="text-align:right;color:#1a1a1a;">${idea.cost_per_contract:.2f}</td>
          <td style="padding:2px 0 2px 16px;">Contracts</td><td style="text-align:right;color:#1a1a1a;">{result.sizing.contracts} (${result.sizing.total_cost:.2f}, {result.sizing.pct_of_portfolio * 100:.0f}%)</td>
        </tr>
        <tr>
          <td style="padding:2px 0;">Max loss</td><td style="text-align:right;color:#c62828;">${idea.max_loss_per_contract:.2f}</td>
          <td style="padding:2px 0 2px 16px;">Max profit</td><td style="text-align:right;color:#2e7d32;">{max_profit}</td>
        </tr>
        <tr>
          <td style="padding:2px 0;">Breakeven</td><td style="text-align:right;color:#1a1a1a;">${idea.breakeven:.2f}</td>
          <td style="padding:2px 0 2px 16px;">DTE</td><td style="text-align:right;color:#1a1a1a;">{idea.dte}</td>
        </tr>
        <tr>
          <td style="padding:2px 0;">Setup confidence</td><td style="text-align:right;color:#1a1a1a;" colspan="3">{idea.confidence * 100:.0f}% (scales size, not a win-probability)</td>
        </tr>
      </table>
      <div style="{FONT}font-size:11px;color:{MUTED};margin-top:8px;font-style:italic;">{_esc(idea.rationale)}</div>
    </div>
    """


def _position_urgency(check: dict) -> tuple[str, str, str]:
    """Returns (bg, fg, label) for the most urgent action on a position."""
    if "error" in check:
        return "#f5f5f5", "#616161", "DATA UNAVAILABLE"
    actions = check.get("actions", [])
    joined = " ".join(actions)
    if "PROFIT TARGET" in joined:
        return "#e3f2fd", "#1565c0", "TAKE PROFIT"
    if "STOP LOSS" in joined:
        return "#ffebee", "#c62828", "CUT LOSS"
    if "DTE LEFT" in joined:
        return "#fff8e1", "#ef6c00", "TIME EXIT"
    return "#f5f5f5", "#616161", "HOLD"


def _position_row(check: dict) -> str:
    p = check["position"]
    bg, fg, label = _position_urgency(check)
    badge = _badge(label, bg, fg)

    if "error" in check:
        detail = f'<span style="color:{MUTED};">{_esc(check["error"])}</span>'
    else:
        pnl_color = "#2e7d32" if check["pnl_pct"] >= 0 else "#c62828"
        detail = (
            f'{check["dte_remaining"]} DTE left &nbsp;·&nbsp; '
            f'<span style="color:{pnl_color};font-weight:700;">{check["pnl_pct"] * 100:+.1f}% '
            f'(${check["pnl_dollars"]:+.2f})</span>'
        )

    return f"""
    <div style="{CARD_BORDER}padding:12px 16px;margin-bottom:10px;">
      <div style="{FONT}font-size:14px;font-weight:700;color:#1a1a2e;">
        {_esc(p.ticker)} &nbsp; {badge}
        <span style="color:{MUTED};font-weight:400;font-size:12px;"> {_esc(p.contracts)}x {_esc(p.structure)} {_esc(p.expiration)}</span>
      </div>
      <div style="{FONT}font-size:12px;color:{MUTED};margin-top:6px;">{detail}</div>
    </div>
    """


def _stat_tile(label: str, value: str, color: str = "#1a1a1a") -> str:
    return f"""
    <td style="{FONT}text-align:center;padding:10px 4px;">
      <div style="font-size:19px;font-weight:700;color:{color};">{_esc(value)}</div>
      <div style="font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:.03em;">{_esc(label)}</div>
    </td>
    """


def _sparkline(df: pd.DataFrame, height: int = 40) -> str:
    if df.empty or len(df) < 2:
        return ""
    tail = df.tail(20)
    values = tail["equity"].astype(float).tolist()
    lo, hi = min(values), max(values)
    spread = hi - lo

    cells = []
    for i, v in enumerate(values):
        bar_h = int(6 + (v - lo) / spread * height) if spread > 0 else height // 2
        is_last = i == len(values) - 1
        color = "#1a1a2e" if is_last else "#90a4ca"
        cells.append(
            f'<td style="vertical-align:bottom;padding:0 1px;">'
            f'<div style="width:10px;height:{bar_h}px;background:{color};border-radius:2px 2px 0 0;"></div>'
            f"</td>"
        )
    return f"""
    <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:10px;">
      <tr>{''.join(cells)}</tr>
    </table>
    <div style="{FONT}font-size:10px;color:{MUTED};margin-top:4px;">
      Rough equity trend, last {len(values)} logged day(s) (realized P/L only, ignores open positions)
    </div>
    """


def _activity_table(rows) -> str:
    if not rows:
        return f'<div style="{FONT}font-size:12px;color:{MUTED};">No activity data available.</div>'
    trs = []
    for i, r in enumerate(rows, start=1):
        pc = f"{r.put_call_ratio:.2f}" if r.put_call_ratio is not None else "n/a"
        bg = "#fafafa" if i % 2 == 0 else "#ffffff"
        trs.append(
            f'<tr style="background:{bg};">'
            f'<td style="padding:6px 8px;color:{MUTED};">{i}</td>'
            f'<td style="padding:6px 8px;font-weight:700;">{_esc(r.ticker)}</td>'
            f'<td style="padding:6px 8px;text-align:right;">${r.price:.2f}</td>'
            f'<td style="padding:6px 8px;text-align:right;">{r.total_volume:,}</td>'
            f'<td style="padding:6px 8px;text-align:right;">{pc}</td>'
            f"</tr>"
        )
    return f"""
    <table role="presentation" width="100%" style="{FONT}font-size:12px;border-collapse:collapse;">
      <tr style="color:{MUTED};font-size:11px;text-transform:uppercase;">
        <td style="padding:4px 8px;">#</td><td style="padding:4px 8px;">Ticker</td>
        <td style="padding:4px 8px;text-align:right;">Price</td>
        <td style="padding:4px 8px;text-align:right;">Volume</td>
        <td style="padding:4px 8px;text-align:right;">P/C</td>
      </tr>
      {''.join(trs)}
    </table>
    """


def render_html(
    cfg: Config,
    results: list,
    position_checks: list,
    scorecard: Scorecard,
    hot_rows: list | None,
    hot_error: str | None,
    equity_df: pd.DataFrame,
) -> str:
    ideas_html = (
        "".join(_idea_card(r) for r in results) if results
        else f'<div style="{FONT}font-size:13px;color:{MUTED};">No ideas cleared every filter today.</div>'
    )

    positions_html = (
        "".join(_position_row(c) for c in position_checks) if position_checks
        else f'<div style="{FONT}font-size:13px;color:{MUTED};">No open tracked positions.</div>'
    )

    pnl_color = "#2e7d32" if scorecard.total_realized_pnl >= 0 else "#c62828"
    track_record_html = ""
    if scorecard.total_closed:
        track_record_html = f"""
        <table role="presentation" width="100%" style="border-collapse:collapse;">
          <tr>
            {_stat_tile("Closed trades", str(scorecard.total_closed))}
            {_stat_tile("Win rate", f"{scorecard.win_rate * 100:.0f}%")}
            {_stat_tile("Total P/L", f"${scorecard.total_realized_pnl:+.2f}", pnl_color)}
            {_stat_tile("Avg return", f"{scorecard.avg_pnl_pct * 100:+.1f}%")}
          </tr>
        </table>
        {_sparkline(equity_df)}
        """
    else:
        track_record_html = f'<div style="{FONT}font-size:13px;color:{MUTED};">No closed positions yet.</div>'

    if hot_error:
        activity_html = f'<div style="{FONT}font-size:12px;color:{MUTED};">Activity check failed: {_esc(hot_error)}</div>'
    else:
        activity_html = _activity_table(hot_rows or [])

    return f"""
    <div style="{FONT}max-width:640px;margin:0 auto;background:#f4f4f7;padding:16px;">
      <div style="background:#1a1a2e;color:#ffffff;padding:18px 22px;border-radius:10px 10px 0 0;">
        <div style="font-size:17px;font-weight:700;">Options Alert Dashboard</div>
        <div style="font-size:12px;color:#c7c7d9;margin-top:4px;">
          Portfolio ${cfg.account.portfolio_value:.2f} &middot; max risk/trade {cfg.account.max_risk_per_trade_pct * 100:.0f}%
          &middot; {len(position_checks)} tracked position(s)
        </div>
      </div>
      <div style="background:#ffffff;border:1px solid #e3e3e8;border-top:none;border-radius:0 0 10px 10px;padding:20px 22px;">
        {_section_title("New Trade Ideas")}
        {ideas_html}

        {_section_title("Open Positions")}
        {positions_html}

        {_section_title("Track Record")}
        {track_record_html}

        {_section_title("Today's Options Activity")}
        {activity_html}

        <div style="{FONT}font-size:10px;color:{MUTED};margin-top:26px;padding-top:14px;border-top:1px solid #eee;line-height:1.5;">
          Options trading involves substantial risk and is not suitable for all investors.
          This is decision support only -- nothing here places real trades, and quotes are
          delayed/best-effort. Not financial advice.
        </div>
      </div>
    </div>
    """
