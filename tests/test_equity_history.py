import shutil
import tempfile
import unittest
from unittest.mock import patch

from src import equity_history
from src.config import load_config, DEFAULT_CONFIG_PATH
from src.scorecard import Scorecard


class TestEquityHistory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.data.cache_dir = self.tmp_dir
        self.cfg.account.portfolio_value = 500.0

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_logs_starting_equity_with_no_closed_trades(self):
        with patch("src.scorecard.compute_scorecard",
                   return_value=Scorecard(total_realized_pnl=0.0)):
            equity_history.log_daily_snapshot(self.cfg)

        df = equity_history.load_equity_history(self.cfg)
        self.assertEqual(len(df), 1)
        self.assertAlmostEqual(df.iloc[0]["equity"], 500.0)

    def test_reflects_realized_pnl(self):
        with patch("src.scorecard.compute_scorecard",
                   return_value=Scorecard(total_realized_pnl=42.5)):
            equity_history.log_daily_snapshot(self.cfg)

        df = equity_history.load_equity_history(self.cfg)
        self.assertAlmostEqual(df.iloc[0]["equity"], 542.5)

    def test_same_day_rerun_updates_instead_of_duplicating(self):
        with patch("src.scorecard.compute_scorecard",
                   return_value=Scorecard(total_realized_pnl=10.0)):
            equity_history.log_daily_snapshot(self.cfg)
        with patch("src.scorecard.compute_scorecard",
                   return_value=Scorecard(total_realized_pnl=20.0)):
            equity_history.log_daily_snapshot(self.cfg)

        df = equity_history.load_equity_history(self.cfg)
        self.assertEqual(len(df), 1)
        self.assertAlmostEqual(df.iloc[0]["equity"], 520.0)

    def test_load_returns_empty_frame_when_no_file(self):
        df = equity_history.load_equity_history(self.cfg)
        self.assertTrue(df.empty)


if __name__ == "__main__":
    unittest.main()
