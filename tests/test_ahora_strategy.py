import random
import unittest

from strategies.my_strategy import (
    _ema_series,
    _sma_series,
    _wma_series,
    get_intrabar_signal,
    get_signal,
)


def make_trending_candles(invert=False, count=45):
    rng = random.Random(42)
    closes = [100.0]
    drift = 0.02
    for index in range(100):
        if index in (55, 70):
            drift = rng.choice((0.05, -0.05, 0.0))
        closes.append(closes[-1] + drift + rng.gauss(0, 0.12))
    if invert:
        closes = [200.0 - value for value in closes]
    rows = []
    for index, close in enumerate(closes[:count]):
        rows.append({
            "timestamp": index * 60,
            "open": close,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
        })
    return rows


class GO2024Tests(unittest.TestCase):
    def test_sma_values(self):
        self.assertEqual(_sma_series([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_wma_weights_newest_value_more(self):
        values = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(_wma_series(values, 3)[-1], 14.0 / 6.0)

    def test_ema_starts_after_period(self):
        result = _ema_series([1.0, 2.0, 3.0, 4.0], 3)
        self.assertIsNone(result[1])
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)

    def test_call_uses_original_cross_and_both_ema_filters(self):
        data = make_trending_candles(count=45)
        result = get_intrabar_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["stage"], "INTRABAR")
        self.assertEqual(len(result["reasons"]), 3)

    def test_closed_candle_confirmation(self):
        data = make_trending_candles(count=46)
        result = get_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["stage"], "CLOSED")

    def test_put_uses_original_cross_and_both_ema_filters(self):
        data = make_trending_candles(invert=True, count=45)
        result = get_intrabar_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")

    def test_insufficient_history_does_not_signal(self):
        self.assertIsNone(get_intrabar_signal(make_trending_candles(count=44)))


if __name__ == "__main__":
    unittest.main()
