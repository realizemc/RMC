import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src import market_regime
from src.config import load_config, DEFAULT_CONFIG_PATH


def _trending_history(direction="up", n=120):
    if direction == "up":
        prices = np.linspace(100, 200, n)
    else:
        prices = np.linspace(200, 100, n)
    return pd.DataFrame({"Close": prices}, index=pd.date_range("2023-01-01", periods=n))


class TestGetMarketDirection(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)

    def test_bullish_when_reference_uptrending(self):
        with patch("src.market_regime.data_mod.get_price_history", return_value=_trending_history("up")):
            self.assertEqual(market_regime.get_market_direction(self.cfg), "bullish")

    def test_bearish_when_reference_downtrending(self):
        with patch("src.market_regime.data_mod.get_price_history", return_value=_trending_history("down")):
            self.assertEqual(market_regime.get_market_direction(self.cfg), "bearish")

    def test_neutral_on_empty_history(self):
        with patch("src.market_regime.data_mod.get_price_history", return_value=pd.DataFrame()):
            self.assertEqual(market_regime.get_market_direction(self.cfg), "neutral")

    def test_neutral_on_insufficient_history(self):
        short_history = _trending_history("up", n=10)
        with patch("src.market_regime.data_mod.get_price_history", return_value=short_history):
            self.assertEqual(market_regime.get_market_direction(self.cfg), "neutral")

    def test_uses_configured_reference_ticker(self):
        self.cfg.market_regime.reference_ticker = "QQQ"
        with patch("src.market_regime.data_mod.get_price_history", return_value=_trending_history("up")) as mock_hist:
            market_regime.get_market_direction(self.cfg)
        mock_hist.assert_called_once_with("QQQ", period=self.cfg.data.price_history_period)


if __name__ == "__main__":
    unittest.main()
