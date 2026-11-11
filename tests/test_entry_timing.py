import unittest

from entry_timing import filter_market_assets, is_intrabar_entry_window


class EntryTimingTests(unittest.TestCase):
    def test_intrabar_window_accepts_three_and_two_seconds(self):
        self.assertTrue(is_intrabar_entry_window(3.0))
        self.assertTrue(is_intrabar_entry_window(2.0))
        self.assertTrue(is_intrabar_entry_window(2.5))

    def test_intrabar_window_rejects_outside_boundaries(self):
        self.assertFalse(is_intrabar_entry_window(3.01))
        self.assertFalse(is_intrabar_entry_window(1.99))
        self.assertFalse(is_intrabar_entry_window(10.0))
        self.assertFalse(is_intrabar_entry_window(None))


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
