"""End-to-end pipeline test against synthetic data.

Yahoo Finance isn't reachable from every environment (corporate proxies,
sandboxes, offline dev), so this monkeypatches the data layer instead of
hitting the network, and exercises strategy -> screener -> alerts and the
backtester against fabricated but internally-consistent price/chain data.
"""
import datetime as dt
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src import alerts, backtest as backtest_mod, data as data_mod
from src.config import load_config, DEFAULT_CONFIG_PATH
from src.screener import run_screen


def _make_bullish_history(n=300, seed=42):
    rng = np.random.default_rng(seed)
    trend = np.linspace(0, 40, n)
    noise = np.cumsum(rng.normal(0, 0.8, n))
    prices = 50 + trend + noise
    idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq="B")
    return pd.DataFrame({"Close": prices}, index=idx)


def _make_option_chain(S: float, expiration: str):
    strikes = np.round(np.arange(S * 0.7, S * 1.3, S * 0.025), 2)
    rows = []
    for k in strikes:
        rows.append({
            "contractSymbol": f"TEST{expiration.replace('-', '')}C{int(k * 1000):08d}",
            "strike": float(k),
            "lastPrice": max(S - k, 1.0),
            "bid": max(S - k, 0.5) * 0.98,
            "ask": max(S - k, 0.5) * 1.02,
            "volume": 500,
            "openInterest": 1000,
            "impliedVolatility": 0.45,
            "inTheMoney": k < S,
        })
    calls = pd.DataFrame(rows)

    put_rows = []
    for k in strikes:
        put_rows.append({
            "contractSymbol": f"TEST{expiration.replace('-', '')}P{int(k * 1000):08d}",
            "strike": float(k),
            "lastPrice": max(k - S, 1.0),
            "bid": max(k - S, 0.5) * 0.98,
            "ask": max(k - S, 0.5) * 1.02,
            "volume": 500,
            "openInterest": 1000,
            "impliedVolatility": 0.45,
            "inTheMoney": k > S,
        })
    puts = pd.DataFrame(put_rows)
    return calls, puts


class TestSyntheticPipeline(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.watchlist = ["FAKEUP"]
        self.history = _make_bullish_history()
        self.S = float(self.history["Close"].iloc[-1])
        self.expiration = (dt.date.today() + dt.timedelta(days=35)).isoformat()
        self.calls, self.puts = _make_option_chain(self.S, self.expiration)

    def _snapshot(self, ticker, expiration, underlying_price=None):
        return data_mod.OptionChainSnapshot(
            ticker=ticker,
            underlying_price=underlying_price or self.S,
            expiration=expiration,
            dte=35,
            calls=self.calls.copy(),
            puts=self.puts.copy(),
        )

    def test_screener_produces_a_sized_idea_from_synthetic_bullish_ticker(self):
        with patch("src.data.get_price_history", return_value=self.history), \
             patch("src.data.expirations_in_dte_window", return_value=[self.expiration]), \
             patch("src.data.get_option_chain", side_effect=self._snapshot), \
             patch("src.data.get_next_earnings_date", return_value=None):

            results, reasons = run_screen(self.cfg, verbose=False)

        self.assertEqual(reasons["FAKEUP"], "ok")
        self.assertEqual(len(results), 1)
        idea = results[0].idea
        self.assertEqual(idea.direction, "bullish")
        self.assertIn(idea.structure, ("long_call", "call_debit_spread"))
        self.assertGreater(results[0].sizing.contracts, 0)
        self.assertLessEqual(results[0].sizing.total_cost, self.cfg.account.max_trade_cost_usd + 1e-6)

        # Output formatting shouldn't blow up on a real idea.
        text = alerts.format_console(results)
        self.assertIn("FAKEUP", text)
        self.assertIn("BUY", text)

    def test_earnings_before_expiration_blocks_the_trade(self):
        earnings_date = dt.date.today() + dt.timedelta(days=10)  # inside the 35 DTE window
        with patch("src.data.get_price_history", return_value=self.history), \
             patch("src.data.expirations_in_dte_window", return_value=[self.expiration]), \
             patch("src.data.get_option_chain", side_effect=self._snapshot), \
             patch("src.data.get_next_earnings_date", return_value=earnings_date):

            results, reasons = run_screen(self.cfg, verbose=False)

        self.assertEqual(results, [])
        self.assertIn("earnings", reasons["FAKEUP"])

    def test_earnings_after_expiration_does_not_block_the_trade(self):
        earnings_date = dt.date.today() + dt.timedelta(days=60)  # after the 35 DTE expiration
        with patch("src.data.get_price_history", return_value=self.history), \
             patch("src.data.expirations_in_dte_window", return_value=[self.expiration]), \
             patch("src.data.get_option_chain", side_effect=self._snapshot), \
             patch("src.data.get_next_earnings_date", return_value=earnings_date):

            results, reasons = run_screen(self.cfg, verbose=False)

        self.assertEqual(reasons["FAKEUP"], "ok")
        self.assertEqual(len(results), 1)

    def test_screener_returns_nothing_when_trend_is_flat(self):
        flat = pd.DataFrame(
            {"Close": np.full(300, 50.0)},
            index=pd.date_range(end=pd.Timestamp.today(), periods=300, freq="B"),
        )
        with patch("src.data.get_price_history", return_value=flat):
            results, reasons = run_screen(self.cfg, verbose=False)

        self.assertEqual(results, [])
        self.assertNotEqual(reasons["FAKEUP"], "ok")

    def test_backtest_runs_end_to_end_on_synthetic_history(self):
        long_history = _make_bullish_history(n=900, seed=7)
        with patch("src.data.get_price_history", return_value=long_history):
            result = backtest_mod.run_backtest(self.cfg, tickers=["FAKEUP"], years=3)

        self.assertGreater(result.starting_capital, 0)
        self.assertGreater(result.ending_equity, 0)
        # A sustained synthetic uptrend should produce at least one long-call trade.
        self.assertGreaterEqual(len(result.trades), 1)
        for t in result.trades:
            self.assertIn(t.exit_reason, ("profit_target", "stop_loss", "time_exit", "expired", "backtest_end"))


if __name__ == "__main__":
    unittest.main()
