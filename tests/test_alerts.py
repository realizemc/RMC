import unittest

from src import alerts
from src.positions import Position


def _fake_position():
    return Position(
        id="p1", ticker="SOFI", structure="long_call", expiration="2026-08-30",
        long_strike=10.0, short_strike=None, long_contract_symbol="X",
        short_contract_symbol=None, entry_cost_per_contract=100.0, contracts=1,
        entry_date="2026-07-01",
    )


class TestFormatPositionChecks(unittest.TestCase):
    def test_no_positions_message(self):
        self.assertEqual(alerts.format_position_checks([]), "No open tracked positions.")

    def test_shows_theta_line_when_present(self):
        checks = [{
            "position": _fake_position(), "dte_remaining": 20,
            "current_value_per_contract": 100.0, "pnl_pct": 0.0, "pnl_dollars": 0.0,
            "theta_per_contract": -1.34, "theta_pct_of_value": 0.0134,
            "actions": ["HOLD -- no exit rule triggered"],
        }]
        text = alerts.format_position_checks(checks)
        self.assertIn("Theta decay", text)
        self.assertIn("$-1.34/day", text)
        self.assertIn("1.3%/day", text)

    def test_omits_theta_line_when_absent(self):
        checks = [{
            "position": _fake_position(), "dte_remaining": 20,
            "current_value_per_contract": 100.0, "pnl_pct": 0.0, "pnl_dollars": 0.0,
            "actions": ["HOLD -- no exit rule triggered"],
        }]
        text = alerts.format_position_checks(checks)
        self.assertNotIn("Theta decay", text)

    def test_error_check_shows_error_not_theta(self):
        checks = [{"position": _fake_position(), "error": "chain unavailable"}]
        text = alerts.format_position_checks(checks)
        self.assertIn("ERROR: chain unavailable", text)
        self.assertNotIn("Theta decay", text)


if __name__ == "__main__":
    unittest.main()
