import unittest
from unittest.mock import patch

from signal_engine import analyze


class DemexCustomEngineIntegrationTests(unittest.TestCase):
    def test_custom_strategy_signal_is_accepted_without_rsi_field(self):
        signal = {
            "direction": "CALL",
            "confidence": 100,
            "reasons": ["Bollinger, retração e toque na C2"],
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
