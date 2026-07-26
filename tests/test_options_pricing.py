import unittest

from src.options_pricing import bs_delta, bs_price, implied_volatility


class TestBSPrice(unittest.TestCase):
    def test_put_call_parity(self):
        S, K, T, r, sigma = 100.0, 100.0, 0.5, 0.045, 0.30
        call = bs_price(S, K, T, r, sigma, "call")
        put = bs_price(S, K, T, r, sigma, "put")
        # C - P = S - K*e^(-rT)
        lhs = call - put
        rhs = S - K * pow(2.718281828, -r * T)
        self.assertAlmostEqual(lhs, rhs, places=2)

    def test_call_price_increases_with_underlying(self):
        base = bs_price(100, 100, 0.5, 0.045, 0.3, "call")
        higher = bs_price(110, 100, 0.5, 0.045, 0.3, "call")
        self.assertGreater(higher, base)

    def test_put_price_increases_as_underlying_falls(self):
        base = bs_price(100, 100, 0.5, 0.045, 0.3, "put")
        lower_S = bs_price(90, 100, 0.5, 0.045, 0.3, "put")
        self.assertGreater(lower_S, base)

    def test_price_nonnegative(self):
        self.assertGreaterEqual(bs_price(50, 200, 0.1, 0.045, 0.2, "call"), 0.0)
        self.assertGreaterEqual(bs_price(200, 50, 0.1, 0.045, 0.2, "put"), 0.0)


class TestBSDelta(unittest.TestCase):
    def test_call_delta_in_zero_one(self):
        d = bs_delta(100, 100, 0.5, 0.045, 0.3, "call")
        self.assertGreater(d, 0.0)
        self.assertLess(d, 1.0)

    def test_put_delta_in_neg_one_zero(self):
        d = bs_delta(100, 100, 0.5, 0.045, 0.3, "put")
        self.assertLess(d, 0.0)
        self.assertGreater(d, -1.0)

    def test_deep_itm_call_delta_near_one(self):
        d = bs_delta(200, 50, 0.25, 0.045, 0.25, "call")
        self.assertGreater(d, 0.9)

    def test_deep_otm_call_delta_near_zero(self):
        d = bs_delta(50, 200, 0.25, 0.045, 0.25, "call")
        self.assertLess(d, 0.1)


class TestImpliedVol(unittest.TestCase):
    def test_round_trip_recovers_sigma(self):
        S, K, T, r, sigma = 100.0, 105.0, 0.3, 0.045, 0.42
        price = bs_price(S, K, T, r, sigma, "call")
        recovered = implied_volatility(price, S, K, T, r, "call")
        self.assertIsNotNone(recovered)
        self.assertAlmostEqual(recovered, sigma, places=3)


if __name__ == "__main__":
    unittest.main()
