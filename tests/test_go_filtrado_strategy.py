import math
import unittest

from strategies import my_strategy as strategy


class GoFiltradoStrategyTests(unittest.TestCase):
    def candles(self, count=120):
        rows = []
        price = 1.0
        for index in range(count):
            drift = 0.0008 if index < count // 2 else -0.0002
            wave = math.sin(index / 3.0) * 0.0015
            close = price + drift + wave
            rows.append({
                "open": price,
                "high": max(price, close) + 0.001,
                "low": min(price, close) - 0.001,
                "close": close,
                "timestamp": index * 60,
            })
            price = close
        return rows

    def test_indicator_parameters_match_uploaded_lua(self):
        self.assertEqual(strategy.FAST_PERIOD, 1)
        self.assertEqual(strategy.SLOW_PERIOD, 34)
        self.assertEqual(strategy.SIGNAL_PERIOD, 5)
        self.assertEqual(strategy.EMA_FILTER_PERIOD, 21)
        self.assertEqual(strategy.EMA_TREND_PERIOD, 45)
        self.assertEqual(strategy.ADX_PERIOD, 14)
        self.assertEqual(strategy.ADX_SMOOTHING_PERIOD, 27)
        self.assertEqual(strategy.ADX_MINIMUM, 35.0)

    def test_ema_uses_27_period_smoothing_for_adx_components(self):
        values = [float(i) for i in range(60)]
        result = strategy._ema_series(values, 27)
        self.assertIsNone(result[25])
        self.assertAlmostEqual(result[26], sum(values[:27]) / 27)
        self.assertIsNotNone(result[-1])

    def test_adx_is_not_available_before_its_smoothing_warmup(self):
        rows = self.candles(52)
        adx = strategy._adx_series(rows, 14)
        self.assertTrue(all(value is None for value in adx))

    def test_adx_is_calculated_after_warmup(self):
        rows = self.candles(120)
        adx = strategy._adx_series(rows, 14)
        self.assertIsNotNone(adx[-1])
        self.assertGreaterEqual(adx[-1], 0.0)
        self.assertLessEqual(adx[-1], 100.0)

    def test_intrabar_signal_requires_at_least_60_candles(self):
        self.assertIsNone(strategy.get_intrabar_signal(self.candles(59)))
        result = strategy.get_intrabar_signal(self.candles(120))
        self.assertTrue(result is None or result["direction"] in ("CALL", "PUT"))

    def test_closed_signal_discards_last_incomplete_candle(self):
        self.assertIsNone(strategy.get_signal(self.candles(60)))
        result = strategy.get_signal(self.candles(120))
        self.assertTrue(result is None or result["direction"] in ("CALL", "PUT"))


if __name__ == "__main__":
    unittest.main()
