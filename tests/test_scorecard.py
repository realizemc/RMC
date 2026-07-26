import shutil
import tempfile
import unittest

from src.config import load_config, DEFAULT_CONFIG_PATH
from src.positions import Position, save_positions
from src.scorecard import compute_scorecard, summarize


def _pos(**overrides):
    defaults = dict(
        id="p", ticker="SOFI", structure="long_call", expiration="2026-08-30",
        long_strike=9.5, short_strike=None, long_contract_symbol="X",
        short_contract_symbol=None, entry_cost_per_contract=50.0, contracts=1,
        entry_date="2026-07-01", status="closed", close_date="2026-07-15",
    )
    defaults.update(overrides)
    return Position(**defaults)


class TestScorecard(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        self.cfg.alerts.log_dir = self.tmp_dir

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_empty_scorecard(self):
        sc = compute_scorecard(self.cfg)
        self.assertEqual(sc.total_closed, 0)
        self.assertIn("No closed positions", summarize(sc))

    def test_aggregates_wins_and_losses(self):
        positions = [
            _pos(id="a", realized_pnl_dollars=30.0, realized_pnl_pct=0.6),
            _pos(id="b", realized_pnl_dollars=-25.0, realized_pnl_pct=-0.5),
            _pos(id="c", realized_pnl_dollars=10.0, realized_pnl_pct=0.2),
        ]
        save_positions(self.cfg, positions)

        sc = compute_scorecard(self.cfg)
        self.assertEqual(sc.total_closed, 3)
        self.assertEqual(sc.priced_closed, 3)
        self.assertEqual(sc.wins, 2)
        self.assertAlmostEqual(sc.win_rate, 2 / 3)
        self.assertAlmostEqual(sc.total_realized_pnl, 15.0)

        text = summarize(sc, starting_capital=500.0)
        self.assertIn("515.00", text)  # 500 + 15 realized

    def test_unpriced_closed_positions_excluded_but_counted(self):
        positions = [
            _pos(id="a", realized_pnl_dollars=30.0, realized_pnl_pct=0.6),
            _pos(id="b", realized_pnl_dollars=None, realized_pnl_pct=None),
        ]
        save_positions(self.cfg, positions)

        sc = compute_scorecard(self.cfg)
        self.assertEqual(sc.total_closed, 2)
        self.assertEqual(sc.priced_closed, 1)
        self.assertAlmostEqual(sc.total_realized_pnl, 30.0)
        self.assertIn("1 closed position(s) have no recorded exit price", summarize(sc))

    def test_open_positions_not_counted(self):
        positions = [_pos(id="a", status="open", realized_pnl_dollars=None)]
        save_positions(self.cfg, positions)
        sc = compute_scorecard(self.cfg)
        self.assertEqual(sc.total_closed, 0)


if __name__ == "__main__":
    unittest.main()
