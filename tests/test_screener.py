import unittest
from unittest.mock import patch

from src.config import load_config, DEFAULT_CONFIG_PATH
from src.screener import run_screen
from src.strategy import OptionLeg, TradeIdea


def _make_idea(ticker, direction="bullish", cost=50.0, recent_returns=None, confidence=1.0):
    leg = OptionLeg(strike=100.0, bid=cost / 100 - 0.05, ask=cost / 100 + 0.05, mid=cost / 100,
                     delta=0.45, iv=0.4, open_interest=500, volume=100, contract_symbol=f"{ticker}X")
    return TradeIdea(
        ticker=ticker, direction=direction, structure="long_call" if direction == "bullish" else "long_put",
        expiration="2026-08-30", dte=35, underlying_price=100.0, long_leg=leg, short_leg=None,
        cost_per_contract=cost, max_loss_per_contract=cost, max_profit_per_contract=None,
        breakeven=105.0, iv_rank_proxy=30.0, rsi=55.0, rationale="test idea",
        recent_returns=recent_returns if recent_returns is not None else [],
        confidence=confidence,
    )


def _fake_evaluate(ideas_by_ticker):
    def _inner(ticker, cfg):
        idea = ideas_by_ticker.get(ticker)
        if idea is None:
            return None, "no signal"
        return idea, "ok"
    return _inner


class TestScreenerDiversification(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.account.portfolio_value = 500.0
        self.cfg.account.max_risk_per_trade_pct = 0.5
        self.cfg.account.max_trade_cost_usd = 500.0
        self.cfg.account.max_open_positions = 3
        self.cfg.account.max_correlation = 0.7
        # Real market-regime check hits the network; keep these tests offline
        # and focused on diversification/sizing logic.
        regime_patcher = patch("src.screener.market_regime_mod.get_market_direction", return_value="neutral")
        regime_patcher.start()
        self.addCleanup(regime_patcher.stop)

    def test_highly_correlated_same_direction_is_skipped(self):
        returns = [0.01, -0.02, 0.03, 0.015, -0.01, 0.02] * 5
        self.cfg.watchlist = ["A", "B"]
        ideas = {
            "A": _make_idea("A", "bullish", cost=50.0, recent_returns=returns),
            "B": _make_idea("B", "bullish", cost=60.0, recent_returns=returns),
        }
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)):
            results, reasons = run_screen(self.cfg)

        tickers = [r.idea.ticker for r in results]
        self.assertEqual(tickers, ["A"])  # cheaper one wins the slot
        self.assertIn("too correlated", reasons["B"])

    def test_opposite_direction_correlation_is_not_flagged(self):
        returns = [0.01, -0.02, 0.03, 0.015, -0.01, 0.02] * 5
        self.cfg.watchlist = ["A", "B"]
        ideas = {
            "A": _make_idea("A", "bullish", cost=50.0, recent_returns=returns),
            "B": _make_idea("B", "bearish", cost=60.0, recent_returns=returns),
        }
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)):
            results, reasons = run_screen(self.cfg)

        tickers = {r.idea.ticker for r in results}
        self.assertEqual(tickers, {"A", "B"})
        self.assertEqual(reasons["B"], "ok")

    def test_uncorrelated_same_direction_both_accepted(self):
        returns_a = [0.02, -0.01, 0.015, -0.02, 0.01, 0.03] * 5
        returns_b = [-0.02, 0.03, -0.01, 0.02, -0.015, -0.01] * 5
        self.cfg.watchlist = ["A", "B"]
        ideas = {
            "A": _make_idea("A", "bullish", cost=50.0, recent_returns=returns_a),
            "B": _make_idea("B", "bullish", cost=60.0, recent_returns=returns_b),
        }
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)):
            results, reasons = run_screen(self.cfg)

        tickers = {r.idea.ticker for r in results}
        self.assertEqual(tickers, {"A", "B"})

    def test_short_return_history_does_not_block_a_trade(self):
        self.cfg.watchlist = ["A", "B"]
        ideas = {
            "A": _make_idea("A", "bullish", cost=50.0, recent_returns=[0.01, 0.02]),
            "B": _make_idea("B", "bullish", cost=60.0, recent_returns=[0.01, 0.02]),
        }
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)):
            results, reasons = run_screen(self.cfg)

        # Not enough overlapping data to compute a trustworthy correlation --
        # fails open rather than blocking trades on bad data.
        tickers = {r.idea.ticker for r in results}
        self.assertEqual(tickers, {"A", "B"})

    def test_max_open_positions_reason_recorded_for_excess_candidates(self):
        self.cfg.watchlist = ["A", "B"]
        self.cfg.account.max_open_positions = 1
        ideas = {
            "A": _make_idea("A", "bullish", cost=50.0),
            "B": _make_idea("B", "bearish", cost=60.0),
        }
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)):
            results, reasons = run_screen(self.cfg)

        self.assertEqual(len(results), 1)
        self.assertIn("max_open_positions already filled", reasons["B"])


class TestScreenerMarketRegime(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.account.portfolio_value = 500.0
        self.cfg.account.max_risk_per_trade_pct = 0.5
        self.cfg.account.max_trade_cost_usd = 500.0
        self.cfg.account.max_open_positions = 3
        self.cfg.market_regime.enabled = True

    def test_bearish_idea_skipped_when_market_is_bullish(self):
        self.cfg.watchlist = ["A"]
        ideas = {"A": _make_idea("A", "bearish", cost=50.0)}
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)), \
             patch("src.screener.market_regime_mod.get_market_direction", return_value="bullish"):
            results, reasons = run_screen(self.cfg)

        self.assertEqual(results, [])
        self.assertIn("broad market", reasons["A"])
        self.assertIn("SPY", reasons["A"])

    def test_bullish_idea_accepted_when_market_is_bullish(self):
        self.cfg.watchlist = ["A"]
        ideas = {"A": _make_idea("A", "bullish", cost=50.0)}
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)), \
             patch("src.screener.market_regime_mod.get_market_direction", return_value="bullish"):
            results, reasons = run_screen(self.cfg)

        self.assertEqual(len(results), 1)

    def test_both_directions_allowed_when_market_is_neutral(self):
        self.cfg.watchlist = ["A", "B"]
        ideas = {
            "A": _make_idea("A", "bullish", cost=50.0),
            "B": _make_idea("B", "bearish", cost=60.0),
        }
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)), \
             patch("src.screener.market_regime_mod.get_market_direction", return_value="neutral"):
            results, reasons = run_screen(self.cfg)

        tickers = {r.idea.ticker for r in results}
        self.assertEqual(tickers, {"A", "B"})

    def test_disabled_skips_the_check_entirely(self):
        self.cfg.market_regime.enabled = False
        self.cfg.watchlist = ["A"]
        ideas = {"A": _make_idea("A", "bearish", cost=50.0)}
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)), \
             patch("src.screener.market_regime_mod.get_market_direction") as mock_regime:
            results, _ = run_screen(self.cfg)

        mock_regime.assert_not_called()
        self.assertEqual(len(results), 1)


class TestScreenerConfidenceSizing(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.account.portfolio_value = 500.0
        self.cfg.account.max_risk_per_trade_pct = 0.20   # base budget = $100
        self.cfg.account.max_trade_cost_usd = 500.0
        self.cfg.account.max_open_positions = 3
        self.cfg.account.confidence_size_floor_pct = 0.7  # weak setup budget = $70
        regime_patcher = patch("src.screener.market_regime_mod.get_market_direction", return_value="neutral")
        regime_patcher.start()
        self.addCleanup(regime_patcher.stop)

    def test_high_confidence_gets_more_contracts_than_low_confidence(self):
        self.cfg.watchlist = ["STRONG"]
        ideas = {"STRONG": _make_idea("STRONG", cost=40.0, confidence=1.0)}
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)):
            results, _ = run_screen(self.cfg)
        self.assertEqual(results[0].sizing.contracts, 2)  # floor(100/40)

        self.cfg.watchlist = ["WEAK"]
        ideas = {"WEAK": _make_idea("WEAK", cost=40.0, confidence=0.0)}
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)):
            results, _ = run_screen(self.cfg)
        self.assertEqual(results[0].sizing.contracts, 1)  # floor(70/40)

    def test_reason_recorded_when_confidence_scaling_causes_budget_miss(self):
        self.cfg.watchlist = ["WEAK"]
        # Costs $75/contract: fits the full $100 budget but not the
        # confidence-scaled $70 budget for a zero-confidence setup.
        ideas = {"WEAK": _make_idea("WEAK", cost=75.0, confidence=0.0)}
        with patch("src.screener.evaluate_ticker", side_effect=_fake_evaluate(ideas)):
            results, reasons = run_screen(self.cfg)

        self.assertEqual(results, [])
        self.assertIn("didn't fit budget", reasons["WEAK"])


if __name__ == "__main__":
    unittest.main()
