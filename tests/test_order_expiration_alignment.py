import unittest
from unittest.mock import patch

import bullex_connector
from bullex_connector import OrderRejectedError, ensure_entry_deadline, resolve_order_expiration


class EntryDeadlineTests(unittest.TestCase):
    def test_three_seconds_exactly_is_allowed(self):
        ensure_entry_deadline(3603.0, 3603.0)

    def test_more_than_three_seconds_is_rejected(self):
        with self.assertRaises(OrderRejectedError):
            ensure_entry_deadline(3603.001, 3603.0)


class ExpirationAlignmentTests(unittest.TestCase):
    def test_expiration_must_match_the_close_of_next_candle(self):
        with patch.object(bullex_connector, "get_expiration_time", return_value=(3660, 0)):
            expiration, expiry_index = resolve_order_expiration(3600.5, 1, 3660)
        self.assertEqual(expiration, 3660)
        self.assertEqual(expiry_index, 0)

    def test_wrong_expiration_blocks_order(self):
        with patch.object(bullex_connector, "get_expiration_time", return_value=(3720, 1)):
            with self.assertRaises(OrderRejectedError):
                resolve_order_expiration(3600.5, 1, 3660)


    def test_real_bullex_expiration_function_uses_next_minute_during_first_three_seconds(self):
        minute_start = 1_800_000_000.0
        minute_start = (int(minute_start // 60) * 60)
        for elapsed in (0.0, 0.5, 3.0):
            with self.subTest(elapsed=elapsed):
                expiration, expiry_index = bullex_connector.get_expiration_time(
                    minute_start + elapsed, 1
                )
                self.assertEqual(expiration, minute_start + 60)
                self.assertEqual(expiry_index, 0)

if __name__ == "__main__":
    unittest.main()
