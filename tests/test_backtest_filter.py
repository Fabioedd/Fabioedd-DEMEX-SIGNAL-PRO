import unittest
from unittest.mock import patch

from backtest_filter import evaluate_backtest


def candle(ts, open_=1.0, close=1.1):
    return {"timestamp": ts, "open": open_, "high": max(open_, close),
            "low": min(open_, close), "close": close}


class BacktestFilterTests(unittest.TestCase):
    def test_approves_only_above_70_percent_and_minimum_sample(self):
        # 23 inputs -> 22 closed candles -> 6 possible historical signals.
        candles = [candle(i * 60) for i in range(23)]
        with patch("backtest_filter.get_signal", return_value={"direction": "CALL"}):
            result = evaluate_backtest(candles, minimum_trades=5)
        self.assertTrue(result["approved"])
        self.assertEqual(result["trades"], 6)
        self.assertEqual(result["win_rate"], 100.0)

    def test_blocks_insufficient_sample(self):
        candles = [candle(i * 60) for i in range(23)]
        with patch("backtest_filter.get_signal", return_value={"direction": "CALL"}):
            result = evaluate_backtest(candles, minimum_trades=7)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "amostra_insuficiente")

    def test_blocks_rate_equal_to_70_percent(self):
        candles = [candle(i * 60, 1.0, 1.1) for i in range(27)]
        # Ten signals: exactly seven wins and three losses = 70%, which must be blocked.
        for index in (23, 24, 25):
            candles[index] = candle(index * 60, 1.1, 1.0)
        with patch("backtest_filter.get_signal", return_value={"direction": "CALL"}):
            result = evaluate_backtest(candles, minimum_trades=5)
        self.assertFalse(result["approved"])
        self.assertEqual(result["trades"], 10)
        self.assertEqual(result["win_rate"], 70.0)


if __name__ == "__main__":
    unittest.main()
