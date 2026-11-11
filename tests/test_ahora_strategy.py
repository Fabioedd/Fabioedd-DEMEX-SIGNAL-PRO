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
        # M15 anterior: 3 candles M5 em 9900, 10200 e 10500.
        self.previous_m15 = [
            candle(9900, 9.0, 10.0, 8.0, 9.5),
            candle(10200, 9.5, 12.0, 9.0, 11.0),
            candle(10500, 11.0, 11.5, 9.0, 10.0),
        ]

    def test_green_candle_touching_c1_is_put(self):
        signal_candle = candle(10800, 11.0, 12.2, 11.2, 11.8)
        forming_candle = candle(11100, 11.8, 12.0, 11.5, 11.7)

        result = get_signal(self.previous_m15 + [signal_candle, forming_candle])

        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertEqual(result["stage"], "CLOSED")

    def test_red_candle_touching_c2_is_call(self):
        signal_candle = candle(10800, 9.0, 9.2, 7.8, 8.5)
        forming_candle = candle(11100, 8.5, 8.8, 8.2, 8.6)

        result = get_signal(self.previous_m15 + [signal_candle, forming_candle])

        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")

    def test_no_signal_when_previous_m15_is_incomplete(self):
        candles = [
            self.previous_m15[1],
            self.previous_m15[2],
            candle(10800, 11.0, 12.2, 11.2, 11.8),
            candle(11100, 11.8, 12.0, 11.5, 11.7),
        ]

        self.assertIsNone(get_signal(candles))

    def test_intrabar_uses_current_candle(self):
        current = candle(10800, 11.0, 12.2, 11.2, 11.8)

        result = get_intrabar_signal(self.previous_m15 + [current])

        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertEqual(result["stage"], "INTRABAR")


if __name__ == "__main__":
    unittest.main()
