import unittest
from unittest.mock import patch

from strategies import my_strategy


class BacktestStrategyTests(unittest.TestCase):
    def candles(self):
        rows = [{"open": 1.0, "close": 1.0} for _ in range(22)]
        rows[16] = {"open": 1.0, "close": 2.0}  # CALL vence
        rows[17] = {"open": 2.0, "close": 1.0}  # PUT vence
        return rows

    def test_backtest_compares_signals_with_the_following_candle(self):
        def fake_signal(prefix, config):
            if len(prefix) == 17:
                return {"direction": "CALL"}
            if len(prefix) == 18:
                return {"direction": "PUT"}
            return None

        with patch.object(my_strategy, "get_signal", side_effect=fake_signal):
            result = my_strategy.backtest_strategy(self.candles(), {})

        self.assertEqual(result["signals"], 2)
        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["losses"], 0)
        self.assertEqual(result["accuracy"], 100.0)

    def test_backtest_returns_zero_when_there_are_no_historical_signals(self):
        with patch.object(my_strategy, "get_signal", return_value=None):
            result = my_strategy.backtest_strategy(self.candles(), {})

        self.assertEqual(result["signals"], 0)
        self.assertEqual(result["accuracy"], 0.0)

    def test_ties_are_excluded_from_accuracy_denominator(self):
        rows = self.candles()
        rows[16] = {"open": 1.0, "close": 1.0}

        def fake_signal(prefix, config):
            if len(prefix) == 17:
                return {"direction": "CALL"}
            return None

        with patch.object(my_strategy, "get_signal", side_effect=fake_signal):
            result = my_strategy.backtest_strategy(rows, {})

        self.assertEqual(result["ties"], 1)
        self.assertEqual(result["accuracy"], 0.0)


if __name__ == "__main__":
    unittest.main()
