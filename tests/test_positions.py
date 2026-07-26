import datetime as dt
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.config import load_config, DEFAULT_CONFIG_PATH
from src import data as data_mod
from src import positions as positions_mod
from src.options_pricing import bs_theta


def _fake_scan(cost_per_contract=55.0, contracts=2, short_leg=None):
    return {
        "ideas": [{
            "ticker": "SOFI",
            "structure": "long_call",
            "expiration": "2026-08-30",
            "long_leg": {"strike": 9.5, "contract_symbol": "SOFI260830C00009500"},
            "short_leg": short_leg,
            "cost_per_contract": cost_per_contract,
            "contracts": contracts,
        }]
    }


class TestPositions(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.alerts.log_dir = self.tmp_dir

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_position_from_scan_persists(self):
        pos = positions_mod.add_position_from_scan(self.cfg, _fake_scan(), 0)
        loaded = positions_mod.load_positions(self.cfg)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, pos.id)
        self.assertEqual(loaded[0].ticker, "SOFI")
        self.assertEqual(loaded[0].contracts, 2)
        self.assertEqual(loaded[0].status, "open")

    def test_close_with_manual_fill_price_computes_realized_pnl(self):
        pos = positions_mod.add_position_from_scan(self.cfg, _fake_scan(cost_per_contract=55.0, contracts=2), 0)
        ok = positions_mod.close_position(self.cfg, pos.id, fill_price_per_contract=88.0)
        self.assertTrue(ok)

        loaded = positions_mod.load_positions(self.cfg)[0]
        self.assertEqual(loaded.status, "closed")
        self.assertEqual(loaded.exit_source, "manual fill price")
        self.assertAlmostEqual(loaded.realized_pnl_dollars, (88.0 - 55.0) * 2)
        self.assertAlmostEqual(loaded.realized_pnl_pct, (88.0 - 55.0) / 55.0)

    def test_close_without_fill_price_falls_back_to_live_estimate(self):
        pos = positions_mod.add_position_from_scan(self.cfg, _fake_scan(cost_per_contract=50.0, contracts=1), 0)
        fake_check = {
            "position": pos,
            "dte_remaining": 20,
            "current_value_per_contract": 75.0,
            "pnl_pct": 0.5,
            "pnl_dollars": 25.0,
            "actions": ["HOLD -- no exit rule triggered"],
        }
        with patch("src.positions.check_position", return_value=fake_check):
            ok = positions_mod.close_position(self.cfg, pos.id)
        self.assertTrue(ok)

        loaded = positions_mod.load_positions(self.cfg)[0]
        self.assertEqual(loaded.exit_source, "live model estimate")
        self.assertAlmostEqual(loaded.realized_pnl_dollars, 25.0)

    def test_close_without_pricing_available_leaves_pnl_unset(self):
        pos = positions_mod.add_position_from_scan(self.cfg, _fake_scan(), 0)
        with patch("src.positions.check_position", return_value={"position": pos, "error": "chain unavailable"}):
            ok = positions_mod.close_position(self.cfg, pos.id, note="closed manually, no data")
        self.assertTrue(ok)

        loaded = positions_mod.load_positions(self.cfg)[0]
        self.assertEqual(loaded.status, "closed")
        self.assertIsNone(loaded.realized_pnl_dollars)
        self.assertEqual(loaded.close_note, "closed manually, no data")

    def test_close_nonexistent_id_returns_false(self):
        self.assertFalse(positions_mod.close_position(self.cfg, "doesnotexist"))


class TestCheckPositionTheta(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.exp = (dt.date.today() + dt.timedelta(days=20)).isoformat()

    def _snapshot(self, calls=None, puts=None, dte=20, S=10.05):
        empty = pd.DataFrame({"contractSymbol": [], "strike": [], "bid": [], "ask": [], "impliedVolatility": []})
        return data_mod.OptionChainSnapshot(
            ticker="SOFI", underlying_price=S, expiration=self.exp, dte=dte,
            calls=calls if calls is not None else empty,
            puts=puts if puts is not None else empty,
        )

    def _long_call_position(self):
        return positions_mod.Position(
            id="p1", ticker="SOFI", structure="long_call", expiration=self.exp,
            long_strike=10.0, short_strike=None, long_contract_symbol="X",
            short_contract_symbol=None, entry_cost_per_contract=100.0, contracts=1,
            entry_date="2026-07-01",
        )

    def test_theta_fields_present_and_negative_for_long_call(self):
        calls = pd.DataFrame({"contractSymbol": ["X"], "strike": [10.0], "bid": [0.95], "ask": [1.05],
                               "impliedVolatility": [0.55]})
        pos = self._long_call_position()
        with patch("src.positions.get_option_chain", return_value=self._snapshot(calls=calls)):
            result = positions_mod.check_position(self.cfg, pos)

        self.assertIsNotNone(result["theta_per_contract"])
        self.assertLess(result["theta_per_contract"], 0.0)
        self.assertGreater(result["theta_pct_of_value"], 0.0)

    def test_debit_spread_theta_is_smaller_magnitude_than_naked_long(self):
        calls = pd.DataFrame({
            "contractSymbol": ["LONG", "SHORT"], "strike": [10.0, 12.0],
            "bid": [0.95, 0.30], "ask": [1.05, 0.40], "impliedVolatility": [0.55, 0.50],
        })
        naked_pos = positions_mod.Position(
            id="p1", ticker="SOFI", structure="long_call", expiration=self.exp,
            long_strike=10.0, short_strike=None, long_contract_symbol="LONG",
            short_contract_symbol=None, entry_cost_per_contract=100.0, contracts=1,
            entry_date="2026-07-01",
        )
        spread_pos = positions_mod.Position(
            id="p2", ticker="SOFI", structure="call_debit_spread", expiration=self.exp,
            long_strike=10.0, short_strike=12.0, long_contract_symbol="LONG",
            short_contract_symbol="SHORT", entry_cost_per_contract=70.0, contracts=1,
            entry_date="2026-07-01",
        )

        with patch("src.positions.get_option_chain", return_value=self._snapshot(calls=calls)):
            naked_result = positions_mod.check_position(self.cfg, naked_pos)
            spread_result = positions_mod.check_position(self.cfg, spread_pos)

        self.assertLess(
            abs(spread_result["theta_per_contract"]),
            abs(naked_result["theta_per_contract"]),
        )

    def test_calendar_mode_ignores_theta_pct(self):
        self.cfg.exits.exit_rule_mode = "calendar"
        self.cfg.exits.close_by_dte = 10
        calls = pd.DataFrame({"contractSymbol": ["X"], "strike": [10.0], "bid": [0.10], "ask": [0.15],
                               "impliedVolatility": [0.55]})
        pos = self._long_call_position()
        # Fast-decaying near-expiry contract, but plenty of DTE left relative
        # to close_by_dte, so calendar mode should stay quiet about theta.
        with patch("src.positions.get_option_chain", return_value=self._snapshot(calls=calls, dte=20)):
            result = positions_mod.check_position(self.cfg, pos)

        self.assertFalse(any("THETA" in a for a in result["actions"]))

    def test_theta_pct_mode_triggers_close_to_expiration(self):
        self.cfg.exits.exit_rule_mode = "theta_pct"
        self.cfg.exits.theta_pct_of_value = 0.05
        near_exp = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        calls = pd.DataFrame({"contractSymbol": ["X"], "strike": [10.0], "bid": [0.20], "ask": [0.30],
                               "impliedVolatility": [0.55]})
        pos = positions_mod.Position(
            id="p1", ticker="SOFI", structure="long_call", expiration=near_exp,
            long_strike=10.0, short_strike=None, long_contract_symbol="X",
            short_contract_symbol=None, entry_cost_per_contract=100.0, contracts=1,
            entry_date="2026-07-01",
        )
        snap = data_mod.OptionChainSnapshot(
            ticker="SOFI", underlying_price=10.05, expiration=near_exp, dte=3, calls=calls,
            puts=pd.DataFrame({"contractSymbol": [], "strike": [], "bid": [], "ask": [], "impliedVolatility": []}),
        )
        with patch("src.positions.get_option_chain", return_value=snap):
            result = positions_mod.check_position(self.cfg, pos)

        self.assertTrue(any("THETA ACCELERATING" in a for a in result["actions"]))


class TestAddManualPosition(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.alerts.log_dir = self.tmp_dir
        self.exp = "2026-08-30"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _snapshot(self):
        calls = pd.DataFrame({
            "contractSymbol": ["SOFI260830C00009500", "SOFI260830C00012000"],
            "strike": [9.5, 12.0], "bid": [0.52, 0.20], "ask": [0.58, 0.26],
            "impliedVolatility": [0.52, 0.48],
        })
        puts = pd.DataFrame({
            "contractSymbol": ["SOFI260830P00009500"], "strike": [9.5],
            "bid": [0.40], "ask": [0.46], "impliedVolatility": [0.50],
        })
        return data_mod.OptionChainSnapshot(
            ticker="SOFI", underlying_price=9.60, expiration=self.exp, dte=35, calls=calls, puts=puts,
        )

    def test_long_call_success_finds_real_contract_symbol(self):
        with patch("src.positions.get_option_chain", return_value=self._snapshot()):
            pos, reason = positions_mod.add_manual_position(
                self.cfg, ticker="sofi", structure="long_call", expiration=self.exp,
                long_strike=9.5, entry_cost_per_contract=55.0, contracts=2,
            )
        self.assertEqual(reason, "ok")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.ticker, "SOFI")
        self.assertEqual(pos.long_contract_symbol, "SOFI260830C00009500")
        self.assertIsNone(pos.short_contract_symbol)
        self.assertEqual(pos.contracts, 2)
        loaded = positions_mod.load_positions(self.cfg)
        self.assertEqual(len(loaded), 1)

    def test_debit_spread_success_finds_both_contract_symbols(self):
        with patch("src.positions.get_option_chain", return_value=self._snapshot()):
            pos, reason = positions_mod.add_manual_position(
                self.cfg, ticker="SOFI", structure="call_debit_spread", expiration=self.exp,
                long_strike=9.5, short_strike=12.0, entry_cost_per_contract=32.0, contracts=1,
            )
        self.assertEqual(reason, "ok")
        self.assertEqual(pos.long_contract_symbol, "SOFI260830C00009500")
        self.assertEqual(pos.short_contract_symbol, "SOFI260830C00012000")

    def test_invalid_structure_rejected(self):
        pos, reason = positions_mod.add_manual_position(
            self.cfg, ticker="SOFI", structure="iron_condor", expiration=self.exp,
            long_strike=9.5, entry_cost_per_contract=55.0, contracts=1,
        )
        self.assertIsNone(pos)
        self.assertIn("structure must be one of", reason)

    def test_spread_without_short_strike_rejected(self):
        pos, reason = positions_mod.add_manual_position(
            self.cfg, ticker="SOFI", structure="call_debit_spread", expiration=self.exp,
            long_strike=9.5, entry_cost_per_contract=32.0, contracts=1,
        )
        self.assertIsNone(pos)
        self.assertIn("requires a short_strike", reason)

    def test_long_only_with_short_strike_rejected(self):
        pos, reason = positions_mod.add_manual_position(
            self.cfg, ticker="SOFI", structure="long_call", expiration=self.exp,
            long_strike=9.5, short_strike=12.0, entry_cost_per_contract=55.0, contracts=1,
        )
        self.assertIsNone(pos)
        self.assertIn("doesn't take a short_strike", reason)

    def test_wrong_side_spread_strike_rejected(self):
        # Selling a strike BELOW the long strike on a call spread is backwards.
        with patch("src.positions.get_option_chain", return_value=self._snapshot()):
            pos, reason = positions_mod.add_manual_position(
                self.cfg, ticker="SOFI", structure="call_debit_spread", expiration=self.exp,
                long_strike=12.0, short_strike=9.5, entry_cost_per_contract=32.0, contracts=1,
            )
        self.assertIsNone(pos)
        self.assertIn("invalid call_debit_spread", reason)

    def test_strike_not_on_chain_rejected(self):
        with patch("src.positions.get_option_chain", return_value=self._snapshot()):
            pos, reason = positions_mod.add_manual_position(
                self.cfg, ticker="SOFI", structure="long_call", expiration=self.exp,
                long_strike=50.0, entry_cost_per_contract=55.0, contracts=1,
            )
        self.assertIsNone(pos)
        self.assertIn("no call contract found", reason)

    def test_chain_unavailable_rejected(self):
        with patch("src.positions.get_option_chain", return_value=None):
            pos, reason = positions_mod.add_manual_position(
                self.cfg, ticker="BADTICKER", structure="long_call", expiration=self.exp,
                long_strike=9.5, entry_cost_per_contract=55.0, contracts=1,
            )
        self.assertIsNone(pos)
        self.assertIn("could not load", reason)


if __name__ == "__main__":
    unittest.main()
