import unittest

from strategies.my_strategy import get_intrabar_signal, get_signal


def candle(ts, open_, high, low, close):
    return {"timestamp": ts, "open": open_, "high": high, "low": low, "close": close}


class ScriptAhoraRsiTests(unittest.TestCase):
    def candles_for_put(self):
        data = []
        # Vela M15 anterior: 15 candles com máxima 102.
        for i in range(15):
            data.append(candle(i * 60, 100, 102, 99, 101))
        # Primeira vela da nova M15: verde, toca C1; RSI permanece sobrecomprado.
        data.append(candle(900, 101, 102, 100, 101.5))
        # Vela atual em formação.
        data.append(candle(960, 101.5, 102, 101, 101.8))
        return data

    def candles_for_call(self):
        data = []
        # Vela M15 anterior: mínima 98.
        for i in range(15):
            data.append(candle(i * 60, 100, 101, 98, 99))
        # Primeira vela da nova M15: vermelha, toca C2; RSI permanece sobrevendido.
        data.append(candle(900, 99, 99.5, 98, 98.5))
        data.append(candle(960, 98.5, 98.8, 98, 98.2))
        return data

    def test_put_requires_green_touch_c1_and_overbought_rsi(self):
        signal = get_signal(self.candles_for_put(), {"rsi_period": 14})
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "PUT")
        self.assertGreaterEqual(signal["rsi"], 70)

    def test_call_requires_red_touch_c2_and_oversold_rsi(self):
        signal = get_signal(self.candles_for_call(), {"rsi_period": 14})
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "CALL")
        self.assertLessEqual(signal["rsi"], 30)

    def test_intrabar_signal_uses_current_candle(self):
        signal = get_intrabar_signal(self.candles_for_put(), {"rsi_period": 14})
        self.assertIsNotNone(signal)
        self.assertEqual(signal["stage"], "INTRABAR")

    def test_rsi_thresholds_are_configurable(self):
        signal = get_signal(
            self.candles_for_put(),
            {"rsi_period": 14, "rsi_overbought": 101}
        )
        self.assertIsNone(signal)


if __name__ == "__main__":
    unittest.main()
