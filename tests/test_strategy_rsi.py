import unittest
from unittest.mock import patch

from signal_engine import analyze
from strategies.my_strategy import _signal_at


class DemexMacdZeroLineTests(unittest.TestCase):
    def setUp(self):
        self.candles = [{"open": 1.0, "close": 1.1} for _ in range(40)]

    def test_call_cross_below_zero_does_not_need_rsi(self):
        macd_state = (-0.30, -0.20, -0.10, -0.20)
        with patch("strategies.my_strategy._macd_state", return_value=macd_state):
            signal = _signal_at(self.candles, len(self.candles) - 1, "TEST")
        self.assertEqual(signal["direction"], "CALL")
        self.assertNotIn("rsi", signal)
        self.assertIn("abaixo da linha zero", signal["reasons"][0])

    def test_put_cross_above_zero_does_not_need_rsi(self):
        candles = [{"open": 1.1, "close": 1.0} for _ in range(40)]
        macd_state = (0.30, 0.20, 0.10, 0.20)
        with patch("strategies.my_strategy._macd_state", return_value=macd_state):
            signal = _signal_at(candles, len(candles) - 1, "TEST")
        self.assertEqual(signal["direction"], "PUT")
        self.assertNotIn("rsi", signal)
        self.assertIn("acima da linha zero", signal["reasons"][0])

    def test_call_cross_above_zero_is_rejected(self):
        macd_state = (0.10, 0.20, 0.30, 0.20)
        with patch("strategies.my_strategy._macd_state", return_value=macd_state):
            signal = _signal_at(self.candles, len(self.candles) - 1, "TEST")
        self.assertIsNone(signal)

    def test_put_cross_below_zero_is_rejected(self):
        candles = [{"open": 1.1, "close": 1.0} for _ in range(40)]
        macd_state = (-0.10, -0.20, -0.30, -0.20)
        with patch("strategies.my_strategy._macd_state", return_value=macd_state):
            signal = _signal_at(candles, len(candles) - 1, "TEST")
        self.assertIsNone(signal)

    def test_cross_requires_matching_candle_color(self):
        candles = [{"open": 1.1, "close": 1.0} for _ in range(40)]
        macd_state = (-0.30, -0.20, -0.10, -0.20)
        with patch("strategies.my_strategy._macd_state", return_value=macd_state):
            signal = _signal_at(candles, len(candles) - 1, "TEST")
        self.assertIsNone(signal)


class DemexCustomEngineIntegrationTests(unittest.TestCase):
    def test_custom_strategy_signal_is_accepted_without_rsi_field(self):
        signal = {
            "direction": "CALL",
            "confidence": 100,
            "reasons": ["MACD cruzou para cima abaixo de zero"],
        }
        with patch("signal_engine.custom_script_signal", return_value=signal):
            result = analyze([{}] * 30, {
                "strategy_mode": "custom_script",
                "custom_script_path": "strategies/my_strategy.py",
                "minimum_confidence": 70,
            })
        self.assertEqual(result["direction"], "CALL")
        self.assertIsNone(result["rsi"])
        self.assertEqual(result["votes"], 1)

    def test_custom_strategy_rejects_confidence_at_or_below_existing_threshold(self):
        signal = {"direction": "PUT", "confidence": 70, "reasons": []}
        with patch("signal_engine.custom_script_signal", return_value=signal):
            result = analyze([{}] * 30, {
                "strategy_mode": "custom_script",
                "custom_script_path": "strategies/my_strategy.py",
                "minimum_confidence": 70,
            })
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
