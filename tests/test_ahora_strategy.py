import math
import unittest
from unittest.mock import patch

from strategies import my_strategy as strategy


def make_candles(count=120):
    rows = []
    price = 100.0
    for index in range(count):
        change = 0.08 + math.sin(index / 3.0) * 0.04
        close = price + change
        rows.append({
            "timestamp": index * 60,
            "open": price,
            "high": max(price, close) + 0.02,
            "low": min(price, close) - 0.02,
            "close": close,
        })
        price = close
    return rows


def calculated(direction="CALL", adx_value=40.0, count=60):
    buffer1 = [0.0] * count
    buffer2 = [0.0] * count
    ema21 = [2.0] * count
    ema45 = [1.0] * count
    closes = [3.0] * count
    adx = [adx_value] * count
    if direction == "CALL":
        buffer1[-2], buffer2[-2] = 0.1, 0.2
        buffer1[-1], buffer2[-1] = 0.3, 0.2
    else:
        buffer1[-2], buffer2[-2] = 0.3, 0.2
        buffer1[-1], buffer2[-1] = 0.1, 0.2
        ema21 = [2.0] * count
        ema45 = [3.0] * count
        closes = [1.0] * count
    return buffer1, buffer2, ema21, ema45, closes, adx


class GO2024FiltradoTests(unittest.TestCase):
    def test_indicator_parameters_match_lua(self):
        self.assertEqual(strategy.FAST_PERIOD, 1)
        self.assertEqual(strategy.SLOW_PERIOD, 21)
        self.assertEqual(strategy.SIGNAL_PERIOD, 3)
        self.assertEqual(strategy.EMA_FILTER_PERIOD, 21)
        self.assertEqual(strategy.EMA_TREND_PERIOD, 45)
        self.assertEqual(strategy.ADX_PERIOD, 14)
        self.assertEqual(strategy.ADX_SMOOTHING_PERIOD, 27)
        self.assertEqual(strategy.ADX_MINIMUM, 35.0)

    def test_sma_values(self):
        self.assertEqual(strategy._sma_series([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_wma_weights_newest_value_more(self):
        self.assertAlmostEqual(strategy._wma_series([1.0, 2.0, 3.0], 3)[-1], 14.0 / 6.0)

    def test_ema_starts_after_period(self):
        result = strategy._ema_series([1.0, 2.0, 3.0, 4.0], 3)
        self.assertIsNone(result[1])
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)

    def test_call_uses_cross_and_both_ema_filters_with_adx_35(self):
        data = make_candles(60)
        with patch.object(strategy, "_calculate", return_value=calculated("CALL")):
            result = strategy.get_intrabar_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["stage"], "INTRABAR")
        self.assertEqual(len(result["reasons"]), 4)

    def test_put_uses_descending_cross_and_both_ema_filters(self):
        data = make_candles(60)
        with patch.object(strategy, "_calculate", return_value=calculated("PUT")):
            result = strategy.get_intrabar_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")

    def test_closed_candle_confirmation_discards_last_incomplete_candle(self):
        data = make_candles(61)
        with patch.object(strategy, "_calculate", return_value=calculated("CALL")):
            result = strategy.get_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["stage"], "CLOSED")

    def test_adx_below_35_blocks_call_and_put(self):
        for direction in ("CALL", "PUT"):
            data = make_candles(60)
            with self.subTest(direction=direction):
                with patch.object(
                    strategy, "_calculate",
                    return_value=calculated(direction, adx_value=34.99),
                ):
                    self.assertIsNone(strategy.get_intrabar_signal(data))

    def test_unavailable_adx_blocks_signal(self):
        data = make_candles(60)
        values = list(calculated("CALL"))
        values[-1] = [None] * 60
        with patch.object(strategy, "_calculate", return_value=tuple(values)):
            self.assertIsNone(strategy.get_intrabar_signal(data))

    def test_adx_uses_ema_27_smoothing_and_warmup(self):
        self.assertEqual(strategy.ADX_SMOOTHING_PERIOD, 27)
        values = [float(index) for index in range(60)]
        result = strategy._ema_series(values, 27)
        self.assertIsNone(result[25])
        self.assertAlmostEqual(result[26], sum(values[:27]) / 27)
        self.assertIsNotNone(result[-1])

    def test_adx_series_warms_up_then_returns_bounded_value(self):
        self.assertTrue(all(value is None for value in strategy._adx_series(make_candles(52), 14)))
        adx = strategy._adx_series(make_candles(120), 14)
        self.assertIsNotNone(adx[-1])
        self.assertGreaterEqual(adx[-1], 0.0)
        self.assertLessEqual(adx[-1], 100.0)

    def test_insufficient_history_does_not_signal(self):
        self.assertIsNone(strategy.get_intrabar_signal(make_candles(59)))


if __name__ == "__main__":
    unittest.main()
