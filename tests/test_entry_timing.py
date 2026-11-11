import unittest

from entry_timing import (
    closed_signal_entry_mode,
    filter_market_assets,
    is_intrabar_entry_window,
    is_candle_still_open,
)


class EntryTimingTests(unittest.TestCase):
    def test_intrabar_window_accepts_three_and_two_seconds(self):
        self.assertTrue(is_intrabar_entry_window(3.0))
        self.assertTrue(is_intrabar_entry_window(2.0))
        self.assertTrue(is_intrabar_entry_window(2.5))

    def test_intrabar_signal_is_pending_until_candle_closes(self):
        self.assertTrue(is_candle_still_open(30.0))
        self.assertTrue(is_candle_still_open(2.5))
        self.assertFalse(is_candle_still_open(0.0))
        self.assertFalse(is_candle_still_open(-0.1))
        self.assertFalse(is_candle_still_open(None))

    def test_intrabar_window_rejects_outside_boundaries(self):
        self.assertFalse(is_intrabar_entry_window(3.01))
        self.assertFalse(is_intrabar_entry_window(1.99))
        self.assertFalse(is_intrabar_entry_window(10.0))
        self.assertFalse(is_intrabar_entry_window(None))


class ClosedSignalEntryTests(unittest.TestCase):
    def test_closed_signal_can_enter_at_close(self):
        self.assertEqual(closed_signal_entry_mode(0.0), "CLOSE")
        self.assertEqual(closed_signal_entry_mode(0.75), "CLOSE")

    def test_closed_signal_can_enter_within_five_seconds(self):
        self.assertEqual(closed_signal_entry_mode(0.76), "NEXT_CANDLE_DELAY")
        self.assertEqual(closed_signal_entry_mode(2.0), "NEXT_CANDLE_DELAY")
        self.assertEqual(closed_signal_entry_mode(5.0), "NEXT_CANDLE_DELAY")

    def test_late_closed_signal_is_rejected_after_five_seconds(self):
        self.assertIsNone(closed_signal_entry_mode(5.01))
        self.assertIsNone(closed_signal_entry_mode(-0.1))


class AssetDiscoveryTests(unittest.TestCase):
    def test_market_selection_filters_only_otc_type_and_never_payout(self):
        assets = [
            {"symbol": "EURUSD-OTC", "active_id": 1, "payout_percent": 5},
            {"symbol": "EURUSD", "active_id": 2, "payout_percent": 100},
            {"symbol": "GBPUSD-OTC", "active_id": 3},
        ]
        selected = filter_market_assets(assets, "OTC")
        self.assertEqual([a["symbol"] for a in selected], ["EURUSD-OTC", "GBPUSD-OTC"])


if __name__ == "__main__":
    unittest.main()
