import unittest

from strategies.my_strategy import (
    _bollinger_at,
    _m15_previous_levels,
    get_intrabar_signal,
    get_signal,
)


def make_candles(direction="PUT", count=34):
    rows = []
    for index in range(count):
        close = 100.0 + (0.004 if index % 2 else -0.004)
        open_price = close - 0.001
        rows.append({
            "timestamp": index * 60,
            "open": open_price,
            "high": close + 0.005,
            "low": open_price - 0.005,
            "close": close,
        })

    # O M15 anterior (timestamps 900 a 1740) fornece C1/C2.
    for index in range(15, 30):
        rows[index]["high"] = 100.6
        rows[index]["low"] = 99.4

    # A sequência acontece no bloco M15 seguinte.
    if direction == "PUT":
        rows[30].update({"open": 100.0, "high": 101.2, "low": 99.9, "close": 101.0})
        rows[31].update({"open": 101.0, "high": 101.05, "low": 99.9, "close": 100.0})
        rows[32].update({"open": 100.2, "high": 100.6, "low": 100.1, "close": 100.4})
    else:
        rows[30].update({"open": 100.0, "high": 100.1, "low": 98.8, "close": 99.0})
        rows[31].update({"open": 99.0, "high": 100.1, "low": 98.95, "close": 100.0})
        rows[32].update({"open": 99.8, "high": 99.9, "low": 99.4, "close": 99.6})

    return rows


class ScriptAhoraBBTests(unittest.TestCase):
    def test_bollinger_uses_period_20_and_two_deviations(self):
        result = _bollinger_at([float(i) for i in range(20)], 19)
        self.assertIsNotNone(result)
        upper, lower = result
        self.assertGreater(upper, 19.0)
        self.assertLess(lower, 0.0)

    def test_m15_levels_require_all_fifteen_m1_candles(self):
        data = make_candles("PUT")
        levels = _m15_previous_levels(data, 30)
        self.assertIsNotNone(levels)
        self.assertAlmostEqual(levels[0], 100.6)
        self.assertAlmostEqual(levels[1], 99.4)
        incomplete = [row for row in data[:29] if row["timestamp"] != 600]
        self.assertIsNone(_m15_previous_levels(incomplete, len(incomplete) - 1))

    def test_put_requires_upper_band_touch_retracement_then_c1(self):
        result = get_intrabar_signal(make_candles("PUT", count=33))
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertEqual(result["stage"], "INTRABAR")
        self.assertEqual(len(result["reasons"]), 4)

    def test_call_requires_lower_band_touch_retracement_then_c2(self):
        result = get_intrabar_signal(make_candles("CALL", count=33))
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["stage"], "INTRABAR")

    def test_closed_signal_uses_last_completed_candle(self):
        data = make_candles("PUT", count=33)
        data.append({
            "timestamp": 33 * 60,
            "open": 100.0,
            "high": 100.02,
            "low": 99.98,
            "close": 100.0,
        })
        result = get_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertEqual(result["stage"], "CLOSED")

    def test_no_signal_when_retracement_is_missing(self):
        data = make_candles("PUT", count=33)
        # Faz a vela posterior ao toque continuar acima da banda, sem retração.
        data[31].update({"open": 101.0, "high": 101.4, "low": 100.9, "close": 101.3})
        self.assertIsNone(get_intrabar_signal(data))

    def test_sequence_does_not_survive_m15_bucket_change(self):
        data = make_candles("PUT", count=46)
        # Remove o candle de retração do primeiro bloco e tenta tocar C1
        # somente no bloco M15 seguinte; a sequência antiga deve expirar.
        data[31].update({"open": 101.0, "high": 101.4, "low": 100.9, "close": 101.3})
        data[45].update({"open": 100.2, "high": 100.6, "low": 100.1, "close": 100.4})
        self.assertIsNone(get_intrabar_signal(data))


if __name__ == "__main__":
    unittest.main()
