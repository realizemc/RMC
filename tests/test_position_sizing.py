import unittest

from src.position_sizing import size_trade


class TestSizeTrade(unittest.TestCase):
    def test_fits_when_affordable(self):
        result = size_trade(
            cost_per_contract=100.0,
            portfolio_value=500.0,
            max_risk_per_trade_pct=0.20,
            max_trade_cost_usd=150.0,
        )
        self.assertTrue(result.fits)
        self.assertEqual(result.contracts, 1)
        self.assertAlmostEqual(result.total_cost, 100.0)

    def test_rejects_when_too_expensive_for_risk_pct(self):
        result = size_trade(
            cost_per_contract=200.0,
            portfolio_value=500.0,
            max_risk_per_trade_pct=0.20,  # budget = 100
            max_trade_cost_usd=150.0,
        )
        self.assertFalse(result.fits)
        self.assertEqual(result.contracts, 0)

    def test_respects_max_trade_cost_cap(self):
        result = size_trade(
            cost_per_contract=120.0,
            portfolio_value=1000.0,   # 40% would be 400, way more than cap
            max_risk_per_trade_pct=0.40,
            max_trade_cost_usd=150.0,
        )
        self.assertTrue(result.fits)
        self.assertEqual(result.contracts, 1)  # only 1 fits under $150 cap

    def test_committed_capital_reduces_available_budget(self):
        result = size_trade(
            cost_per_contract=100.0,
            portfolio_value=500.0,
            max_risk_per_trade_pct=0.50,  # budget would be 250
            max_trade_cost_usd=300.0,
            committed_capital=450.0,      # only $50 left
        )
        self.assertFalse(result.fits)

    def test_multiple_contracts_when_cheap_enough(self):
        result = size_trade(
            cost_per_contract=30.0,
            portfolio_value=500.0,
            max_risk_per_trade_pct=0.30,  # budget = 150
            max_trade_cost_usd=150.0,
        )
        self.assertTrue(result.fits)
        self.assertEqual(result.contracts, 5)

    def test_invalid_cost_rejected(self):
        result = size_trade(
            cost_per_contract=0.0,
            portfolio_value=500.0,
            max_risk_per_trade_pct=0.20,
            max_trade_cost_usd=150.0,
        )
        self.assertFalse(result.fits)


if __name__ == "__main__":
    unittest.main()
