import unittest

import pandas as pd

from src import html_report
from src.config import load_config, DEFAULT_CONFIG_PATH
from src.most_active import ActivityRow
from src.positions import Position
from src.scorecard import Scorecard
from src.strategy import OptionLeg, TradeIdea
from src.screener import ScreenResult
from src.position_sizing import SizingResult


def _fake_idea(direction="bullish", short_leg=None):
    long_leg = OptionLeg(
        strike=100.0, bid=1.9, ask=2.1, mid=2.0, delta=0.45, iv=0.4,
        open_interest=500, volume=100, contract_symbol="X",
    )
    return TradeIdea(
        ticker="SOFI", direction=direction, structure="long_call" if direction == "bullish" else "long_put",
        expiration="2026-08-30", dte=35, underlying_price=99.0,
        long_leg=long_leg, short_leg=short_leg, cost_per_contract=200.0,
        max_loss_per_contract=200.0, max_profit_per_contract=None, breakeven=102.0,
        iv_rank_proxy=30.0, rsi=55.0, rationale="bullish trend; RSI 55; vol pct 30",
    )


def _fake_result():
    idea = _fake_idea()
    sizing = SizingResult(fits=True, contracts=1, cost_per_contract=200.0, total_cost=200.0,
                           pct_of_portfolio=0.4, reason="ok")
    return ScreenResult(idea=idea, sizing=sizing)


def _fake_position():
    return Position(
        id="p1", ticker="SOFI", structure="long_call", expiration="2026-08-30",
        long_strike=100.0, short_strike=None, long_contract_symbol="X",
        short_contract_symbol=None, entry_cost_per_contract=200.0, contracts=1,
        entry_date="2026-07-01",
    )


class TestHtmlReport(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)

    def test_renders_without_error_when_everything_empty(self):
        html = html_report.render_html(
            self.cfg, [], [], Scorecard(), None, None, pd.DataFrame(columns=["date", "equity"]),
        )
        self.assertIn("Options Alert Dashboard", html)
        self.assertIn("No ideas cleared", html)
        self.assertIn("No open tracked positions", html)

    def test_renders_idea_card_with_key_numbers(self):
        result = _fake_result()
        html = html_report.render_html(
            self.cfg, [result], [], Scorecard(), None, None, pd.DataFrame(columns=["date", "equity"]),
        )
        self.assertIn("SOFI", html)
        self.assertIn("BULLISH", html)
        self.assertIn("$200.00", html)

    def test_renders_position_urgency_badges(self):
        pos = _fake_position()
        checks = [
            {"position": pos, "dte_remaining": 20, "current_value_per_contract": 320.0,
             "pnl_pct": 0.6, "pnl_dollars": 120.0, "actions": ["PROFIT TARGET HIT (+60%) -- consider closing"]},
        ]
        html = html_report.render_html(
            self.cfg, [], checks, Scorecard(), None, None, pd.DataFrame(columns=["date", "equity"]),
        )
        self.assertIn("TAKE PROFIT", html)

    def test_renders_theta_and_theta_urgency_badge(self):
        pos = _fake_position()
        checks = [
            {"position": pos, "dte_remaining": 3, "current_value_per_contract": 25.0,
             "pnl_pct": -0.5, "pnl_dollars": -25.0, "theta_per_contract": -2.8, "theta_pct_of_value": 0.112,
             "actions": ["THETA ACCELERATING (losing 11.2%/day of value) -- consider closing"]},
        ]
        html = html_report.render_html(
            self.cfg, [], checks, Scorecard(), None, None, pd.DataFrame(columns=["date", "equity"]),
        )
        self.assertIn("TIME EXIT", html)
        self.assertIn("theta $-2.80/day", html)

    def test_renders_error_check_gracefully(self):
        pos = _fake_position()
        checks = [{"position": pos, "error": "chain unavailable"}]
        html = html_report.render_html(
            self.cfg, [], checks, Scorecard(), None, None, pd.DataFrame(columns=["date", "equity"]),
        )
        self.assertIn("DATA UNAVAILABLE", html)
        self.assertIn("chain unavailable", html)

    def test_renders_scorecard_stats_and_sparkline(self):
        sc = Scorecard(total_closed=3, priced_closed=3, wins=2, total_realized_pnl=45.0, avg_pnl_pct=0.2)
        equity_df = pd.DataFrame({"date": ["2026-07-01", "2026-07-02", "2026-07-03"], "equity": [500, 520, 545]})
        html = html_report.render_html(
            self.cfg, [], [], sc, None, None, equity_df,
        )
        self.assertIn("$+45.00", html)
        self.assertIn("67%", html)  # win rate 2/3

    def test_renders_activity_rows(self):
        rows = [ActivityRow(ticker="NVDA", price=120.0, expiration="2026-08-14", dte=19,
                             call_volume=1000, put_volume=500, total_volume=1500,
                             open_interest=5000, put_call_ratio=0.5)]
        html = html_report.render_html(
            self.cfg, [], [], Scorecard(), rows, None, pd.DataFrame(columns=["date", "equity"]),
        )
        self.assertIn("NVDA", html)

    def test_renders_hot_error_message(self):
        html = html_report.render_html(
            self.cfg, [], [], Scorecard(), None, "network blip", pd.DataFrame(columns=["date", "equity"]),
        )
        self.assertIn("network blip", html)

    def test_escapes_user_visible_text(self):
        idea = _fake_idea()
        idea.rationale = "<script>alert(1)</script>"
        sizing = SizingResult(fits=True, contracts=1, cost_per_contract=200.0, total_cost=200.0,
                               pct_of_portfolio=0.4, reason="ok")
        result = ScreenResult(idea=idea, sizing=sizing)
        html = html_report.render_html(
            self.cfg, [result], [], Scorecard(), None, None, pd.DataFrame(columns=["date", "equity"]),
        )
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
