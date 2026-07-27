import datetime as dt
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src import backtest as backtest_mod
from src.config import load_config, DEFAULT_CONFIG_PATH


def _make_bullish_history(n=900, seed=7):
    rng = np.random.default_rng(seed)
    trend = np.linspace(0, 40, n)
    noise = np.cumsum(rng.normal(0, 0.8, n))
    prices = 50 + trend + noise
    idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq="B")
    return pd.DataFrame({"Close": prices}, index=idx)


class TestHeldThroughEarnings(unittest.TestCase):
    def test_true_when_earnings_falls_in_window(self):
        entry = dt.date(2026, 1, 1)
        exp = dt.date(2026, 2, 5)
        earnings = [dt.date(2025, 12, 1), dt.date(2026, 1, 20), dt.date(2026, 3, 1)]
        self.assertTrue(backtest_mod._held_through_earnings(entry, exp, earnings))

    def test_false_when_no_earnings_in_window(self):
        entry = dt.date(2026, 1, 1)
        exp = dt.date(2026, 2, 5)
        earnings = [dt.date(2025, 12, 1), dt.date(2026, 3, 1)]
        self.assertFalse(backtest_mod._held_through_earnings(entry, exp, earnings))

    def test_false_with_empty_earnings_list(self):
        self.assertFalse(backtest_mod._held_through_earnings(dt.date(2026, 1, 1), dt.date(2026, 2, 5), []))

    def test_boundary_dates_are_inclusive(self):
        entry = dt.date(2026, 1, 1)
        exp = dt.date(2026, 2, 5)
        self.assertTrue(backtest_mod._held_through_earnings(entry, exp, [entry]))
        self.assertTrue(backtest_mod._held_through_earnings(entry, exp, [exp]))


class TestFetchEarningsHistory(unittest.TestCase):
    def test_returns_empty_list_on_failure(self):
        with patch("src.backtest.data_mod._ticker", side_effect=RuntimeError("network blip")):
            result = backtest_mod._fetch_earnings_history("BADTICKER", years=2)
        self.assertEqual(result, [])

    def test_returns_sorted_dates_from_index(self):
        fake_index = pd.to_datetime(["2026-01-30", "2025-07-29", "2025-10-28"])
        fake_df = pd.DataFrame({"EPS Estimate": [0.1, 0.2, 0.3]}, index=fake_index)

        class FakeTicker:
            def get_earnings_dates(self, limit):
                return fake_df

        with patch("src.backtest.data_mod._ticker", return_value=FakeTicker()):
            result = backtest_mod._fetch_earnings_history("SOFI", years=2)

        self.assertEqual(result, sorted(ts.date() for ts in fake_index))


class TestRunBacktestEarningsAvoidance(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.history = _make_bullish_history()

    def test_earnings_every_cycle_suppresses_all_trades(self):
        self.cfg.strategy.avoid_earnings = True
        # An earnings date shortly after every possible entry day blocks entry
        # regardless of when the signal actually fires. Span the FULL
        # underlying history's calendar range (not just its business-day
        # count), so no tail segment of the backtested window is left
        # uncovered once _build_signal_frame trims to the last `years` years.
        start = self.history.index[0].date()
        end = self.history.index[-1].date()
        every_week = []
        d = start
        while d <= end:
            every_week.append(d)
            d += dt.timedelta(days=7)
        with patch("src.data.get_price_history", return_value=self.history), \
             patch("src.backtest._fetch_earnings_history", return_value=every_week):
            result = backtest_mod.run_backtest(self.cfg, tickers=["FAKEUP"], years=3)

        self.assertEqual(len(result.trades), 0)

    def test_disabling_avoid_earnings_ignores_history(self):
        self.cfg.strategy.avoid_earnings = False
        with patch("src.data.get_price_history", return_value=self.history), \
             patch("src.backtest._fetch_earnings_history") as mock_fetch:
            result = backtest_mod.run_backtest(self.cfg, tickers=["FAKEUP"], years=3)

        mock_fetch.assert_not_called()
        self.assertGreaterEqual(len(result.trades), 1)

    def test_no_earnings_history_behaves_like_no_earnings(self):
        self.cfg.strategy.avoid_earnings = True
        with patch("src.data.get_price_history", return_value=self.history), \
             patch("src.backtest._fetch_earnings_history", return_value=[]):
            result = backtest_mod.run_backtest(self.cfg, tickers=["FAKEUP"], years=3)

        self.assertGreaterEqual(len(result.trades), 1)


if __name__ == "__main__":
    unittest.main()
