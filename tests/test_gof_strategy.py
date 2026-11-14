"""Focused tests for the GO 2024 FILTRADO signal rules."""
import unittest
from unittest.mock import patch

from strategies import my_strategy as strategy


class GoFilteredStrategyTests(unittest.TestCase):
    def test_requested_parameters_are_active(self):
        self.assertEqual(strategy.FAST_PERIOD, 1)
        self.assertEqual(strategy.SLOW_PERIOD, 21)
        self.assertEqual(strategy.SIGNAL_PERIOD, 3)
        self.assertEqual(strategy.EMA_FILTER_PERIOD, 21)
        self.assertEqual(strategy.EMA_TREND_PERIOD, 45)
        self.assertEqual(strategy.ADX_PERIOD, 14)
        self.assertEqual(strategy.ADX_MINIMUM, 35.0)

    def test_call_requires_cross_and_all_filters(self):
        candles = [{} for _ in range(3)]
        calculated = (
            [0.0, 0.0, 2.0],       # buffer1 crosses above buffer2
            [0.0, 1.0, 1.0],
            [100.0, 100.0, 101.0], # EMA 21
            [99.0, 99.0, 100.0],   # EMA 45
            [100.0, 100.0, 102.0], # close
            [36.0, 36.0, 35.1],    # ADX >= 35
        )
        with patch.object(strategy, "_calculate", return_value=calculated):
            signal = strategy._signal_at(candles, 2, "TEST")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "CALL")

    def test_put_requires_cross_and_all_filters(self):
        candles = [{} for _ in range(3)]
        calculated = (
            [0.0, 2.0, 0.0],       # buffer1 crosses below buffer2
            [0.0, 1.0, 1.0],
            [100.0, 100.0, 99.0],  # EMA 21
            [101.0, 101.0, 100.0], # EMA 45
            [100.0, 100.0, 98.0],  # close
            [36.0, 36.0, 35.1],    # ADX >= 35
        )
        with patch.object(strategy, "_calculate", return_value=calculated):
            signal = strategy._signal_at(candles, 2, "TEST")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "PUT")

    def test_adx_below_35_blocks_signal(self):
        candles = [{} for _ in range(3)]
        calculated = (
            [0.0, 0.0, 2.0], [0.0, 1.0, 1.0],
            [100.0, 100.0, 101.0], [99.0, 99.0, 100.0],
            [100.0, 100.0, 102.0], [36.0, 36.0, 34.99],
        )
        with patch.object(strategy, "_calculate", return_value=calculated):
            signal = strategy._signal_at(candles, 2, "TEST")
        self.assertIsNone(signal)


if __name__ == "__main__":
    unittest.main()
