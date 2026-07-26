import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.config import load_config, DEFAULT_CONFIG_PATH
from src.daily import run_daily
from src.notifier import NotifierError
from src.positions import Position


def _fake_position(**overrides):
    defaults = dict(
        id="p1", ticker="SOFI", structure="long_call", expiration="2026-08-30",
        long_strike=9.5, short_strike=None, long_contract_symbol="SOFI260830C00009500",
        short_contract_symbol=None, entry_cost_per_contract=55.0, contracts=2,
        entry_date="2026-07-20",
    )
    defaults.update(overrides)
    return Position(**defaults)


class TestDaily(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.alerts.log_dir = self.tmp_dir
        self.cfg.data.cache_dir = self.tmp_dir
        # Real IV-history logging hits the network per watchlist ticker;
        # keep these tests offline and focused on email/report logic.
        iv_patcher = patch("src.iv_history.log_daily_snapshot", return_value="fake_iv_path")
        iv_patcher.start()
        self.addCleanup(iv_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_no_content_and_send_on_empty_false_skips_email(self):
        self.cfg.notifications.send_on_empty = False
        with patch("src.daily.run_screen", return_value=([], {"AAA": "no trend"})), \
             patch("src.positions.check_all_open", return_value=[]), \
             patch("src.daily.send_email") as mock_send:
            result = run_daily(self.cfg)

        self.assertFalse(result.email_attempted)
        self.assertFalse(result.email_sent)
        mock_send.assert_not_called()

    def test_no_content_and_send_on_empty_true_sends_email(self):
        self.cfg.notifications.send_on_empty = True
        with patch("src.daily.run_screen", return_value=([], {"AAA": "no trend"})), \
             patch("src.positions.check_all_open", return_value=[]), \
             patch("src.daily.send_email") as mock_send:
            result = run_daily(self.cfg)

        self.assertTrue(result.email_attempted)
        self.assertTrue(result.email_sent)
        mock_send.assert_called_once()
        subject_arg = mock_send.call_args[0][0]
        self.assertIn("no new ideas", subject_arg)

    def test_email_error_is_captured_not_raised(self):
        self.cfg.notifications.send_on_empty = True
        with patch("src.daily.run_screen", return_value=([], {})), \
             patch("src.positions.check_all_open", return_value=[]), \
             patch("src.daily.send_email", side_effect=NotifierError("no creds")):
            result = run_daily(self.cfg)

        self.assertTrue(result.email_attempted)
        self.assertFalse(result.email_sent)
        self.assertEqual(result.email_error, "no creds")

    def test_disabled_notifications_never_sends(self):
        self.cfg.notifications.enabled = False
        self.cfg.notifications.send_on_empty = True
        with patch("src.daily.run_screen", return_value=([], {})), \
             patch("src.positions.check_all_open", return_value=[]), \
             patch("src.daily.send_email") as mock_send:
            result = run_daily(self.cfg)

        self.assertFalse(result.email_attempted)
        mock_send.assert_not_called()

    def test_position_checks_included_when_configured(self):
        self.cfg.notifications.include_position_checks = True
        fake_check = {
            "position": _fake_position(),
            "dte_remaining": 20,
            "current_value_per_contract": 60.0,
            "pnl_pct": 0.09,
            "pnl_dollars": 10.0,
            "actions": ["HOLD -- no exit rule triggered"],
        }
        with patch("src.daily.run_screen", return_value=([], {})), \
             patch("src.positions.check_all_open", return_value=[fake_check]) as mock_check, \
             patch("src.daily.send_email"):
            result = run_daily(self.cfg)

        mock_check.assert_called_once()
        self.assertEqual(result.position_checks, [fake_check])
        self.assertIn("OPEN POSITION CHECKS", result.body)
        self.assertIn("SOFI", result.body)

    def test_subject_flags_actionable_positions(self):
        self.cfg.notifications.include_position_checks = True
        fake_check = {
            "position": _fake_position(),
            "dte_remaining": 15,
            "current_value_per_contract": 91.0,
            "pnl_pct": 0.65,
            "pnl_dollars": 72.0,
            "actions": ["PROFIT TARGET HIT (+65%) -- consider closing"],
        }
        with patch("src.daily.run_screen", return_value=([], {})), \
             patch("src.positions.check_all_open", return_value=[fake_check]), \
             patch("src.daily.send_email"):
            result = run_daily(self.cfg)

        self.assertIn("need attention", result.subject)


if __name__ == "__main__":
    unittest.main()
