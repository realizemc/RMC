import unittest

from src.options_pricing import bs_delta, bs_price, bs_theta, implied_volatility, resolve_implied_vol


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


class TestBSTheta(unittest.TestCase):
    def test_long_call_theta_is_negative(self):
        theta = bs_theta(100, 100, 0.1, 0.045, 0.3, "call")
        self.assertLess(theta, 0.0)

    def test_long_put_theta_is_negative_for_atm(self):
        theta = bs_theta(100, 100, 0.1, 0.045, 0.3, "put")
        self.assertLess(theta, 0.0)

    def test_theta_matches_finite_difference_price_decay(self):
        # Repricing 1 day later (all else equal) should lose ~theta dollars.
        S, K, r, sigma = 100.0, 100.0, 0.045, 0.3
        T = 30 / 365.0
        price_today = bs_price(S, K, T, r, sigma, "call")
        price_tomorrow = bs_price(S, K, T - 1 / 365.0, r, sigma, "call")
        theta = bs_theta(S, K, T, r, sigma, "call")
        actual_decay = price_tomorrow - price_today
        self.assertAlmostEqual(theta, actual_decay, places=2)

    def test_decay_accelerates_closer_to_expiration(self):
        far = abs(bs_theta(100, 100, 60 / 365.0, 0.045, 0.3, "call"))
        near = abs(bs_theta(100, 100, 5 / 365.0, 0.045, 0.3, "call"))
        self.assertGreater(near, far)


class TestResolveImpliedVol(unittest.TestCase):
    def test_uses_quoted_iv_when_present_and_valid(self):
        iv = resolve_implied_vol(0.42, mid_price=999, S=100, K=100, T=0.3, r=0.045, option_type="call")
        self.assertEqual(iv, 0.42)

    def test_solves_from_price_when_iv_missing(self):
        price = bs_price(100, 105, 0.3, 0.045, 0.42, "call")
        iv = resolve_implied_vol(None, price, 100, 105, 0.3, 0.045, "call")
        self.assertAlmostEqual(iv, 0.42, places=3)

    def test_solves_from_price_when_iv_is_nan(self):
        price = bs_price(100, 105, 0.3, 0.045, 0.42, "call")
        iv = resolve_implied_vol(float("nan"), price, 100, 105, 0.3, 0.045, "call")
        self.assertAlmostEqual(iv, 0.42, places=3)

    def test_solves_from_price_when_iv_is_zero(self):
        price = bs_price(100, 105, 0.3, 0.045, 0.42, "call")
        iv = resolve_implied_vol(0.0, price, 100, 105, 0.3, 0.045, "call")
        self.assertAlmostEqual(iv, 0.42, places=3)


if __name__ == "__main__":
    unittest.main()
