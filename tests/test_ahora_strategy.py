import unittest
from unittest.mock import patch

from strategies.my_strategy import (
    get_signal, get_intrabar_signal, _ema_series, _wma_series,
)


def candles(count=40, last_open=100.0, last_close=100.5):
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.01
        open_ = close - 0.01
        rows.append({
            "timestamp": index * 60,
            "open": open_,
            "high": max(open_, close) + 0.1,
            "low": min(open_, close) - 0.1,
            "close": close,
        })
    rows[-1]["open"] = last_open
    rows[-1]["close"] = last_close
    return rows


class DemexAlfaStrategyTests(unittest.TestCase):
    def test_call_uses_bullish_cross_below_zero_and_green_candle(self):
        data = candles()
        state = (-0.30, -0.20, -0.10, -0.20)
        with patch("strategies.my_strategy._macd_state", return_value=state):
            result = get_intrabar_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["stage"], "INTRABAR")
        self.assertNotIn("rsi", result)

    def test_put_uses_bearish_cross_above_zero_and_red_candle(self):
        data = candles(last_open=100.5, last_close=100.0)
        state = (0.30, 0.20, 0.10, 0.20)
        with patch("strategies.my_strategy._macd_state", return_value=state):
            result = get_intrabar_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertNotIn("rsi", result)

    def test_call_cross_above_zero_is_rejected(self):
        state = (0.10, 0.20, 0.30, 0.20)
        with patch("strategies.my_strategy._macd_state", return_value=state):
            self.assertIsNone(get_intrabar_signal(candles()))

    def test_put_cross_below_zero_is_rejected(self):
        data = candles(last_open=100.5, last_close=100.0)
        state = (-0.10, -0.20, -0.30, -0.20)
        with patch("strategies.my_strategy._macd_state", return_value=state):
            self.assertIsNone(get_intrabar_signal(data))

    def test_no_signal_without_macd_cross(self):
        state = (-0.30, -0.20, -0.25, -0.20)
        with patch("strategies.my_strategy._macd_state", return_value=state):
            self.assertIsNone(get_intrabar_signal(candles()))

    def test_cross_requires_matching_candle_color(self):
        data = candles(last_open=100.5, last_close=100.0)
        state = (-0.30, -0.20, -0.10, -0.20)
        with patch("strategies.my_strategy._macd_state", return_value=state):
            self.assertIsNone(get_intrabar_signal(data))

    def test_closed_signal_uses_last_completed_candle(self):
        data = candles()
        state = (-0.30, -0.20, -0.10, -0.20)
        with patch("strategies.my_strategy._macd_state", return_value=state) as macd:
            result = get_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["stage"], "CLOSED")
        self.assertEqual(len(macd.call_args.args[0]), len(data) - 1)

    def test_ema_and_wma_helpers_calculate_series(self):
        ema = _ema_series([1, 2, 3, 4], 2)
        self.assertEqual(ema[:1], [None])
        self.assertAlmostEqual(ema[1], 1.5)
        wma = _wma_series([1.0, 2.0, 3.0], 3)
        self.assertAlmostEqual(wma[-1], (1 + 4 + 9) / 6)


if __name__ == "__main__":
    unittest.main()
