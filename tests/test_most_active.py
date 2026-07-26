import unittest
from unittest.mock import patch

import pandas as pd

from src import data as data_mod
from src import most_active
from src.config import load_config, DEFAULT_CONFIG_PATH


def _chain(call_volume, put_volume, call_oi=1000, put_oi=1000):
    calls = pd.DataFrame({"strike": [100.0], "volume": [call_volume], "openInterest": [call_oi]})
    puts = pd.DataFrame({"strike": [100.0], "volume": [put_volume], "openInterest": [put_oi]})
    return data_mod.OptionChainSnapshot(
        ticker="X", underlying_price=100.0, expiration="2026-08-30", dte=35, calls=calls, puts=puts,
    )


class TestMostActive(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.most_active.universe = ["HIGH", "LOW", "BROKEN", "ZEROVOL"]
        self.cfg.most_active.top_n = 2

    def test_ranks_by_total_volume_and_respects_top_n(self):
        def fake_price(ticker):
            return None if ticker == "BROKEN" else 100.0

        def fake_expirations(ticker):
            return [] if ticker == "BROKEN" else ["2026-08-30"]

        def fake_chain(ticker, exp, underlying_price=None):
            volumes = {"HIGH": (5000, 3000), "LOW": (200, 100), "ZEROVOL": (0, 0)}
            call_v, put_v = volumes[ticker]
            return _chain(call_v, put_v)

        with patch("src.data.get_current_price", side_effect=fake_price), \
             patch("src.data.list_expirations", side_effect=fake_expirations), \
             patch("src.data.get_option_chain", side_effect=fake_chain):
            rows = most_active.get_top_active(self.cfg)

        # BROKEN excluded (no price/expirations), ZEROVOL excluded (no activity),
        # top_n=2 keeps just HIGH and LOW, ranked highest volume first.
        self.assertEqual([r.ticker for r in rows], ["HIGH", "LOW"])
        self.assertEqual(rows[0].total_volume, 8000)
        self.assertAlmostEqual(rows[0].put_call_ratio, 3000 / 5000)

    def test_put_call_ratio_none_when_no_call_volume(self):
        def fake_chain(ticker, exp, underlying_price=None):
            return _chain(0, 500)

        with patch("src.data.get_current_price", return_value=100.0), \
             patch("src.data.list_expirations", return_value=["2026-08-30"]), \
             patch("src.data.get_option_chain", side_effect=fake_chain):
            rows = most_active.get_top_active(self.cfg, top_n=1)

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].put_call_ratio)
        self.assertEqual(rows[0].total_volume, 500)

    def test_a_raising_ticker_does_not_abort_the_whole_scan(self):
        def flaky_price(ticker):
            if ticker == "HIGH":
                raise RuntimeError("network blip")
            return 100.0

        def fake_chain(ticker, exp, underlying_price=None):
            return _chain(1000, 500)

        with patch("src.data.get_current_price", side_effect=flaky_price), \
             patch("src.data.list_expirations", return_value=["2026-08-30"]), \
             patch("src.data.get_option_chain", side_effect=fake_chain):
            rows = most_active.get_top_active(self.cfg)

        tickers = [r.ticker for r in rows]
        self.assertNotIn("HIGH", tickers)
        self.assertIn("LOW", tickers)

    def test_format_console_handles_empty(self):
        text = most_active.format_console([])
        self.assertIn("No options activity", text)

    def test_format_console_lists_ranked_rows(self):
        def fake_chain(ticker, exp, underlying_price=None):
            # Distinct volumes per ticker so the top-1 pick is deterministic.
            volumes = {"HIGH": (1000, 500), "LOW": (10, 5), "BROKEN": (10, 5), "ZEROVOL": (10, 5)}
            call_v, put_v = volumes[ticker]
            return _chain(call_v, put_v)

        with patch("src.data.get_current_price", return_value=100.0), \
             patch("src.data.list_expirations", return_value=["2026-08-30"]), \
             patch("src.data.get_option_chain", side_effect=fake_chain):
            rows = most_active.get_top_active(self.cfg, top_n=1)
        text = most_active.format_console(rows)
        self.assertIn("HIGH", text)
        self.assertIn("scan --tickers", text)


if __name__ == "__main__":
    unittest.main()
