import unittest
from unittest.mock import patch

import strategies.my_strategy as sniper


def candle(open_, close, high=None, low=None):
    high = max(open_, close) + 0.2 if high is None else high
    low = min(open_, close) - 0.2 if low is None else low
    return {"open": open_, "close": close, "high": high, "low": low}


class SniperCandlePatternTests(unittest.TestCase):
    def test_bullish_harami(self):
        candles = [candle(10, 8), candle(8.5, 9.5)]
        self.assertEqual(
            sniper.candle_pattern_at(candles, 1),
            {"direction": "CALL", "pattern": "HARAMI"},
        )

    def test_bearish_harami(self):
        candles = [candle(8, 10), candle(9.5, 8.5)]
        self.assertEqual(
            sniper.candle_pattern_at(candles, 1),
            {"direction": "PUT", "pattern": "HARAMI"},
        )

    def test_bullish_engulfing(self):
        candles = [candle(10, 8), candle(7.5, 10.5)]
        self.assertEqual(
            sniper.candle_pattern_at(candles, 1),
            {"direction": "CALL", "pattern": "ENGOLFO"},
        )

    def test_bearish_engulfing(self):
        candles = [candle(8, 10), candle(10.5, 7.5)]
        self.assertEqual(
            sniper.candle_pattern_at(candles, 1),
            {"direction": "PUT", "pattern": "ENGOLFO"},
        )

    def test_invalid_or_missing_previous_candle_has_no_pattern(self):
        self.assertIsNone(sniper.candle_pattern_at([candle(1, 2)], 0))
        self.assertIsNone(sniper.candle_pattern_at([candle(1, 2), {"open": 2}], 1))


class SniperConfluenceTests(unittest.TestCase):
    def _calculated(self, direction):
        # Valores artificiais isolam e verificam a regra de confluência.
        if direction == "CALL":
            return ([0.0, 2.0], [1.0, 1.0], [None, 12.0], [None, 11.0], [None, 13.0])
        return ([2.0, 0.0], [1.0, 1.0], [None, 11.0], [None, 12.0], [None, 10.0])

    def test_call_requires_bullish_pattern_cross_and_both_ema_filters(self):
        candles = [candle(10, 8), candle(8.5, 9.5)]
        with patch.object(sniper, "_calculate", return_value=self._calculated("CALL")):
            signal = sniper._signal_at(candles, 1, "CLOSED")
        self.assertEqual(signal["direction"], "CALL")
        self.assertIn("Padrão de alta: HARAMI", signal["reasons"])

    def test_put_requires_bearish_pattern_cross_and_both_ema_filters(self):
        candles = [candle(8, 10), candle(9.5, 8.5)]
        with patch.object(sniper, "_calculate", return_value=self._calculated("PUT")):
            signal = sniper._signal_at(candles, 1, "CLOSED")
        self.assertEqual(signal["direction"], "PUT")
        self.assertIn("Padrão de baixa: HARAMI", signal["reasons"])

    def test_opposite_pattern_blocks_go_cross(self):
        candles = [candle(8, 10), candle(9.5, 8.5)]
        with patch.object(sniper, "_calculate", return_value=self._calculated("CALL")):
            self.assertIsNone(sniper._signal_at(candles, 1, "CLOSED"))

    def test_missing_pattern_blocks_go_cross(self):
        candles = [candle(10, 8), candle(10, 8)]
        with patch.object(sniper, "_calculate", return_value=self._calculated("CALL")):
            self.assertIsNone(sniper._signal_at(candles, 1, "CLOSED"))

    def test_insufficient_history_does_not_signal(self):
        candles = [candle(1, 2) for _ in range(sniper.EMA_TREND_PERIOD - 1)]
        self.assertIsNone(sniper.get_intrabar_signal(candles))


if __name__ == "__main__":
    unittest.main()
