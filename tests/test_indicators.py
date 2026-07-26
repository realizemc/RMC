import unittest

import numpy as np
import pandas as pd

from src import indicators


def _make_price_series(prices):
    idx = pd.date_range("2023-01-01", periods=len(prices), freq="D")
    return pd.Series(prices, index=idx)


class TestSMA(unittest.TestCase):
    def test_sma_matches_manual_mean(self):
        s = _make_price_series([1, 2, 3, 4, 5])
        result = indicators.sma(s, 3)
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 2.0)
        self.assertAlmostEqual(result.iloc[4], 4.0)


class TestRSI(unittest.TestCase):
    def test_rsi_bounded_0_100(self):
        prices = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 200))
        s = _make_price_series(prices)
        r = indicators.rsi(s, 14)
        self.assertTrue((r.dropna() >= 0).all())
        self.assertTrue((r.dropna() <= 100).all())

    def test_rsi_high_on_pure_uptrend(self):
        prices = np.linspace(100, 200, 60)
        s = _make_price_series(prices)
        r = indicators.rsi(s, 14)
        self.assertGreater(r.iloc[-1], 70)

    def test_rsi_low_on_pure_downtrend(self):
        prices = np.linspace(200, 100, 60)
        s = _make_price_series(prices)
        r = indicators.rsi(s, 14)
        self.assertLess(r.iloc[-1], 30)


class TestTrend(unittest.TestCase):
    def test_bullish_on_strong_uptrend(self):
        prices = np.linspace(100, 300, 120)
        df = pd.DataFrame({"Close": prices}, index=pd.date_range("2023-01-01", periods=120))
        self.assertEqual(indicators.trend_signal(df, sma_fast=10, sma_slow=30), "bullish")

    def test_bearish_on_strong_downtrend(self):
        prices = np.linspace(300, 100, 120)
        df = pd.DataFrame({"Close": prices}, index=pd.date_range("2023-01-01", periods=120))
        self.assertEqual(indicators.trend_signal(df, sma_fast=10, sma_slow=30), "bearish")

    def test_neutral_without_enough_history(self):
        prices = np.linspace(100, 110, 5)
        df = pd.DataFrame({"Close": prices}, index=pd.date_range("2023-01-01", periods=5))
        self.assertEqual(indicators.trend_signal(df, sma_fast=10, sma_slow=30), "neutral")

    def test_trend_series_matches_trend_signal_last_value(self):
        prices = np.linspace(100, 300, 120)
        df = pd.DataFrame({"Close": prices}, index=pd.date_range("2023-01-01", periods=120))
        series = indicators.trend_series(df, sma_fast=10, sma_slow=30)
        self.assertEqual(series.iloc[-1], indicators.trend_signal(df, sma_fast=10, sma_slow=30))


class TestVolatility(unittest.TestCase):
    def test_realized_volatility_nonnegative(self):
        prices = 100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 100))
        s = _make_price_series(prices)
        hv = indicators.realized_volatility(s, window=20)
        self.assertTrue((hv.dropna() >= 0).all())

    def test_hv_percentile_none_on_short_history(self):
        s = _make_price_series(np.linspace(100, 110, 10))
        self.assertIsNone(indicators.hv_percentile(s))

    def test_hv_percentile_within_bounds(self):
        prices = 100 + np.cumsum(np.random.default_rng(2).normal(0, 1, 400))
        s = _make_price_series(prices)
        pct = indicators.hv_percentile(s)
        self.assertIsNotNone(pct)
        self.assertGreaterEqual(pct, 0)
        self.assertLessEqual(pct, 100)


if __name__ == "__main__":
    unittest.main()
