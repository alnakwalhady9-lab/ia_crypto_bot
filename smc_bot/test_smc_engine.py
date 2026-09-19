import unittest

from smc_engine import Candle, find_recent_sweep, market_structure_bias


def candle(index, high, low, close=None):
    close = (high + low) / 2 if close is None else close
    return Candle(index * 60_000, close, high, low, close, (index + 1) * 60_000 - 1)


class SMCEngineTests(unittest.TestCase):
    def test_bullish_liquidity_sweep(self):
        data = [candle(i, 110 + i * 0.1, 100 + i * 0.1) for i in range(20)]
        prior_low = min(c.low for c in data)
        data.append(candle(20, 105, prior_low - 1, prior_low + 0.5))
        result = find_recent_sweep(data, lookback=20, recent=3)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "long")

    def test_structure_requires_matching_highs_and_lows(self):
        data = [
            candle(0, 10, 8), candle(1, 12, 9), candle(2, 11, 10),
            candle(3, 14, 11), candle(4, 12, 10.5), candle(5, 16, 12),
            candle(6, 13, 11.5), candle(7, 18, 13), candle(8, 15, 12.5),
        ]
        self.assertIn(market_structure_bias(data), {"bullish", "neutral"})


if __name__ == "__main__":
    unittest.main()
