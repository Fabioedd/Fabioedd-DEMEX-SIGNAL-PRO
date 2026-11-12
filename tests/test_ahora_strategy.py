import unittest

from strategies.my_strategy import (
    _donchian_previous,
    _m15_current_levels,
    get_intrabar_signal,
    get_signal,
)


def make_candles(direction="PUT", count=31):
    rows = []
    for index in range(count):
        rows.append({
            "timestamp": index * 60,
            "open": 100.0,
            "high": 100.2,
            "low": 99.8,
            "close": 100.05,
        })

    # O candle de sinal fica no bloco M15 iniciado no minuto 30.
    # Os 20 candles anteriores têm máxima 100.2 e mínima 99.8.
    if direction == "PUT":
        rows[30].update({
            "open": 100.3, "high": 100.8, "low": 100.0, "close": 100.1
        })
    else:
        rows[30].update({
            "open": 99.7, "high": 100.0, "low": 99.2, "close": 99.9
        })
    return rows


class ScriptAhoraDonchianTests(unittest.TestCase):
    def test_donchian_uses_only_previous_twenty_candles(self):
        data = make_candles("PUT")
        upper, lower = _donchian_previous(data, 30)
        self.assertAlmostEqual(upper, 100.2)
        self.assertAlmostEqual(lower, 99.8)

    def test_current_m15_levels_include_signal_candle(self):
        data = make_candles("PUT")
        c1, c2, bucket = _m15_current_levels(data, 30)
        self.assertAlmostEqual(c1, 100.8)
        self.assertAlmostEqual(c2, 100.0)
        self.assertEqual(bucket, 1800)

    def test_put_requires_c1_upper_donchian_and_red_close_only(self):
        result = get_intrabar_signal(make_candles("PUT"))
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertEqual(result["stage"], "INTRABAR")
        self.assertEqual(len(result["reasons"]), 3)

    def test_call_requires_c2_lower_donchian_and_green_close_only(self):
        result = get_intrabar_signal(make_candles("CALL"))
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["stage"], "INTRABAR")

    def test_signal_is_rechecked_on_last_closed_candle(self):
        data = make_candles("PUT", count=32)
        result = get_signal(data)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "PUT")
        self.assertEqual(result["stage"], "CLOSED")

    def test_no_signal_when_donchian_confluence_is_missing(self):
        data = make_candles("PUT")
        # O candle não alcança a máxima dos 20 candles anteriores.
        data[30].update({
            "open": 100.15, "high": 100.19, "low": 100.0, "close": 100.1
        })
        self.assertIsNone(get_intrabar_signal(data))

    def test_no_signal_for_doji(self):
        data = make_candles("PUT")
        data[30]["close"] = data[30]["open"]
        self.assertIsNone(get_intrabar_signal(data))


if __name__ == "__main__":
    unittest.main()
