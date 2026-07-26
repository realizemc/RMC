import shutil
import tempfile
import unittest
from unittest.mock import patch

from src.config import load_config, DEFAULT_CONFIG_PATH
from src import positions as positions_mod


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


if __name__ == "__main__":
    unittest.main()
