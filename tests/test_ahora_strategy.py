import unittest

from strategies.my_strategy import get_signal, get_intrabar_signal


def candle(timestamp, open_, high, low, close):
    return {
        "timestamp": timestamp,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }


class ScriptAhoraTests(unittest.TestCase):
    def setUp(self):
        # M15 anterior: quinze candles M1 de 9000 a 9840.
        self.previous_m15 = []
        for minute in range(15):
            high = 12.0 if minute == 6 else 10.0
            low = 7.0 if minute == 9 else 8.0
            self.previous_m15.append(
                candle(9000 + minute * 60, 9.0, high, low, 9.5)
            )

    def test_green_candle_touching_c1_is_put(self):
        signal_candle = candle(9900, 11.0, 12.2, 11.2, 11.8)
        forming_candle = candle(9960, 11.8, 12.0, 11.5, 11.7)
        result = get_signal(self.previous_m15 + [signal_candle, forming_candle])
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertEqual(result["stage"], "CLOSED")

    def test_red_candle_touching_c2_is_call(self):
        signal_candle = candle(9900, 9.0, 9.2, 6.8, 8.5)
        forming_candle = candle(9960, 8.5, 8.8, 8.2, 8.6)
        result = get_signal(self.previous_m15 + [signal_candle, forming_candle])
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")

    def test_no_signal_when_previous_m15_is_incomplete(self):
        incomplete_history = self.previous_m15[1:] + [
            candle(9900, 11.0, 12.2, 11.2, 11.8),
            candle(9960, 11.8, 12.0, 11.5, 11.7),
        ]
        self.assertIsNone(get_signal(incomplete_history))

    def test_intrabar_uses_current_candle(self):
        current = candle(9900, 11.0, 12.2, 11.2, 11.8)
        result = get_intrabar_signal(self.previous_m15 + [current])
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertEqual(result["stage"], "INTRABAR")


if __name__ == "__main__":
    unittest.main()
