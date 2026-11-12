import unittest

from strategies import harami_engolfo_tendencia as strategy


def candle(open_, close):
    return {"open": open_, "close": close, "high": max(open_, close) + 0.2,
            "low": min(open_, close) - 0.2}


class PatternRulesTests(unittest.TestCase):
    def test_bullish_harami(self):
        self.assertEqual(strategy.candle_pattern_at(
            [candle(10, 8), candle(8.5, 9.5)], 1),
            {"direction": "CALL", "pattern": "HARAMI"})

    def test_bearish_harami(self):
        self.assertEqual(strategy.candle_pattern_at(
            [candle(8, 10), candle(9.5, 8.5)], 1),
            {"direction": "PUT", "pattern": "HARAMI"})

    def test_bullish_engulfing(self):
        self.assertEqual(strategy.candle_pattern_at(
            [candle(10, 8), candle(7.5, 10.5)], 1),
            {"direction": "CALL", "pattern": "ENGOLFO"})

    def test_bearish_engulfing(self):
        self.assertEqual(strategy.candle_pattern_at(
            [candle(8, 10), candle(10.5, 7.5)], 1),
            {"direction": "PUT", "pattern": "ENGOLFO"})

    def test_wicks_do_not_change_body_pattern(self):
        candles = [candle(10, 8), candle(8.5, 9.5)]
        candles[0].update(high=20, low=1)
        candles[1].update(high=30, low=2)
        self.assertEqual(strategy.candle_pattern_at(candles, 1)["pattern"], "HARAMI")

    def test_missing_previous_candle_has_no_pattern(self):
        self.assertIsNone(strategy.candle_pattern_at([candle(1, 2)], 0))


class EmaAndSignalTests(unittest.TestCase):
    def test_ema_seed_and_recursion(self):
        values = strategy._ema_series([1.0, 2.0, 3.0, 4.0], 3)
        self.assertIsNone(values[1])
        self.assertAlmostEqual(values[2], 2.0)
        self.assertAlmostEqual(values[3], 3.0)

    def test_call_uses_pattern_and_ema_filters_without_go_cross(self):
        closes = [100.0 + i for i in range(44)]
        candles = [candle(value - 0.5, value) for value in closes]
        candles.append(candle(142.0, 143.0))
        candles[-2] = candle(143.0, 141.0)
        candles[-1] = candle(141.5, 142.5)
        signal = strategy.get_intrabar_signal(candles)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "CALL")
        self.assertEqual(signal["pattern"], "HARAMI")
        self.assertEqual(len(signal["reasons"]), 3)

    def test_put_uses_pattern_and_ema_filters(self):
        closes = [200.0 - i for i in range(44)]
        candles = [candle(value + 0.5, value) for value in closes]
        candles.append(candle(157.0, 158.0))
        candles[-2] = candle(157.0, 159.0)
        candles[-1] = candle(158.5, 157.5)
        signal = strategy.get_intrabar_signal(candles)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "PUT")
        self.assertEqual(signal["pattern"], "HARAMI")

    def test_wrong_trend_blocks_call(self):
        candles = [candle(100 + i, 100 + i) for i in range(44)]
        candles += [candle(143, 141), candle(141.5, 142.5)]
        with unittest.mock.patch.object(strategy, "_ema_series") as ema:
            ema.side_effect = lambda values, period: (
                [None] * (len(values) - 1) + ([143.0] if period == 21 else [144.0])
            )
            self.assertIsNone(strategy.get_intrabar_signal(candles))

    def test_insufficient_history_does_not_signal(self):
        self.assertIsNone(strategy.get_intrabar_signal([candle(1, 2)] * 44))

    def test_closed_signal_discards_forming_candle(self):
        candles = [candle(100 + i, 100 + i) for i in range(45)]
        candles.append(candle(145, 146))
        self.assertEqual(strategy.get_signal(candles), strategy.get_signal_at_index(candles[:-1], 44))


if __name__ == "__main__":
    unittest.main()
