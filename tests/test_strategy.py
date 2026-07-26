import unittest

from src.config import load_config, DEFAULT_CONFIG_PATH
from src.strategy import _confidence_score


class TestConfidenceScore(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(DEFAULT_CONFIG_PATH)
        # rsi_bull band defaults to 45-75 -> center 60, half-width 15
        # iv_rank_max_pct defaults to 65

    def test_centered_rsi_and_zero_iv_rank_gives_max_confidence(self):
        center = (self.cfg.strategy.rsi_bull_min + self.cfg.strategy.rsi_bull_max) / 2
        score = _confidence_score("bullish", center, 0.0, self.cfg)
        self.assertAlmostEqual(score, 1.0)

    def test_edge_rsi_and_max_iv_rank_gives_min_confidence(self):
        score = _confidence_score("bullish", self.cfg.strategy.rsi_bull_min, self.cfg.strategy.iv_rank_max_pct, self.cfg)
        self.assertAlmostEqual(score, 0.0)  # rsi_confidence=0 (band edge), vol_confidence=0 (at the cap)

    def test_score_is_bounded_0_to_1(self):
        for rsi in [0, 20, 45, 60, 75, 100]:
            for iv in [0, 30, 65, 90, 150]:
                score = _confidence_score("bullish", rsi, iv, self.cfg)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

    def test_bearish_band_used_for_bearish_direction(self):
        center = (self.cfg.strategy.rsi_bear_min + self.cfg.strategy.rsi_bear_max) / 2
        score = _confidence_score("bearish", center, 0.0, self.cfg)
        self.assertAlmostEqual(score, 1.0)

    def test_more_centered_rsi_scores_higher_than_edge_rsi_at_same_iv(self):
        center = (self.cfg.strategy.rsi_bull_min + self.cfg.strategy.rsi_bull_max) / 2
        centered_score = _confidence_score("bullish", center, 30.0, self.cfg)
        edge_score = _confidence_score("bullish", self.cfg.strategy.rsi_bull_max, 30.0, self.cfg)
        self.assertGreater(centered_score, edge_score)


if __name__ == "__main__":
    unittest.main()
