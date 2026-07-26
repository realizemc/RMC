import datetime as dt
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src import data as data_mod
from src import iv_history
from src.config import load_config, DEFAULT_CONFIG_PATH


def _make_chain(underlying: float, expiration: str):
    strikes = [underlying - 2, underlying - 1, underlying, underlying + 1, underlying + 2]
    calls = pd.DataFrame({
        "strike": strikes,
        "impliedVolatility": [0.5, 0.48, 0.45, 0.47, 0.49],
    })
    puts = pd.DataFrame({
        "strike": strikes,
        "impliedVolatility": [0.44, 0.42, 0.40, 0.43, 0.46],
    })
    return calls, puts


class TestIVHistory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.data.cache_dir = self.tmp_dir
        self.cfg.watchlist = ["FAKEUP", "BROKEN"]
        self.expiration = (dt.date.today() + dt.timedelta(days=35)).isoformat()
        self.calls, self.puts = _make_chain(50.0, self.expiration)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _snapshot(self, ticker, exp, underlying_price=None):
        if ticker == "BROKEN":
            return None
        return data_mod.OptionChainSnapshot(
            ticker=ticker, underlying_price=underlying_price or 50.0,
            expiration=exp, dte=35, calls=self.calls.copy(), puts=self.puts.copy(),
        )

    def test_logs_atm_iv_and_skips_failures(self):
        with patch("src.data.get_current_price", return_value=50.0), \
             patch("src.data.expirations_in_dte_window", return_value=[self.expiration]), \
             patch("src.data.get_option_chain", side_effect=self._snapshot):
            path = iv_history.log_daily_snapshot(self.cfg)

        df = pd.read_csv(path)
        self.assertEqual(len(df), 1)  # BROKEN ticker skipped, no crash
        self.assertEqual(df.iloc[0]["ticker"], "FAKEUP")
        self.assertAlmostEqual(df.iloc[0]["atm_iv"], (0.45 + 0.40) / 2, places=3)

    def test_appends_across_multiple_runs(self):
        with patch("src.data.get_current_price", return_value=50.0), \
             patch("src.data.expirations_in_dte_window", return_value=[self.expiration]), \
             patch("src.data.get_option_chain", side_effect=self._snapshot):
            iv_history.log_daily_snapshot(self.cfg)
            path = iv_history.log_daily_snapshot(self.cfg)

        df = pd.read_csv(path)
        self.assertEqual(len(df), 2)

    def test_no_rows_when_price_unavailable(self):
        with patch("src.data.get_current_price", return_value=None):
            path = iv_history.log_daily_snapshot(self.cfg)
        self.assertFalse(__import__("os").path.exists(path))

    def test_a_single_ticker_exception_does_not_abort_the_run(self):
        def flaky_price(ticker):
            if ticker == "FAKEUP":
                raise RuntimeError("network blip")
            return 50.0

        with patch("src.data.get_current_price", side_effect=flaky_price), \
             patch("src.data.expirations_in_dte_window", return_value=[self.expiration]), \
             patch("src.data.get_option_chain", side_effect=self._snapshot):
            path = iv_history.log_daily_snapshot(self.cfg)  # must not raise

        # FAKEUP raised, BROKEN has no chain -- both excluded, no rows, no crash.
        self.assertFalse(__import__("os").path.exists(path))


if __name__ == "__main__":
    unittest.main()
