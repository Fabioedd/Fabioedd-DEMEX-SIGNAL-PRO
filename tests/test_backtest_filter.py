import unittest
from unittest.mock import patch

from backtest_filter import evaluate_backtest


def candle(ts, open_=1.0, close=1.1):
    return {"timestamp": ts, "open": open_, "high": max(open_, close),
            "low": min(open_, close), "close": close}


class BacktestFilterTests(unittest.TestCase):
    def test_approves_single_historical_trade_when_rate_is_above_70(self):
        # Mesmo com apenas uma operação histórica, a assertividade >70% aprova.
        candles = [candle(i * 60) for i in range(23)]
        signals = [None, None, None, None, None, {"direction": "CALL"}]
        with patch("backtest_filter.get_signal", side_effect=signals):
            result = evaluate_backtest(candles)
        self.assertTrue(result["approved"])
        self.assertEqual(result["trades"], 1)
        self.assertEqual(result["win_rate"], 100.0)

    def test_blocks_rate_equal_to_70_percent(self):
        candles = [candle(i * 60, 1.0, 1.1) for i in range(27)]
        # Ten signals: exactly seven wins and three losses = 70%, which must be blocked.
        for index in (23, 24, 25):
            candles[index] = candle(index * 60, 1.1, 1.0)
        with patch("backtest_filter.get_signal", return_value={"direction": "CALL"}):
            result = evaluate_backtest(candles)
        self.assertFalse(result["approved"])
        self.assertEqual(result["trades"], 10)
        self.assertEqual(result["win_rate"], 70.0)

    def test_blocks_when_there_are_no_decisive_historical_trades(self):
        candles = [candle(i * 60) for i in range(23)]
        with patch("backtest_filter.get_signal", return_value=None):
            result = evaluate_backtest(candles)
        self.assertFalse(result["approved"])
        self.assertEqual(result["reason"], "sem_operacoes_validas")
        self.assertEqual(result["trades"], 0)


if __name__ == "__main__":
    unittest.main()
