import unittest
from unittest.mock import patch

from signal_engine import analyze


class DemexAlfaEngineIntegrationTests(unittest.TestCase):
    def test_custom_strategy_signal_is_accepted_without_extra_trend_filter(self):
        signal = {
            "direction": "CALL",
            "confidence": 100,
            "rsi": 24.5,
            "reasons": ["MACD 7/25 cruzou acima da WMA 5", "RSI(14) abaixo de 30"],
        }
        with patch("signal_engine.custom_script_signal", return_value=signal):
            result = analyze([{}] * 30, {
                "strategy_mode": "custom_script",
                "custom_script_path": "strategies/my_strategy.py",
                "minimum_confidence": 70,
            })
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["rsi"], 24.5)
        self.assertEqual(result["votes"], 1)

    def test_custom_strategy_rejects_confidence_at_or_below_existing_threshold(self):
        signal = {"direction": "PUT", "confidence": 70, "rsi": 75.0, "reasons": []}
        with patch("signal_engine.custom_script_signal", return_value=signal):
            result = analyze([{}] * 30, {
                "strategy_mode": "custom_script",
                "custom_script_path": "strategies/my_strategy.py",
                "minimum_confidence": 70,
            })
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
