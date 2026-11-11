import unittest
from unittest.mock import Mock

import main


class EntryTimingTests(unittest.TestCase):
    def test_intrabar_window_accepts_three_and_two_seconds(self):
        self.assertTrue(main.intrabar_entry_window(3.0))
        self.assertTrue(main.intrabar_entry_window(2.0))
        self.assertTrue(main.intrabar_entry_window(2.5))

    def test_intrabar_window_rejects_outside_boundaries(self):
        self.assertFalse(main.intrabar_entry_window(3.01))
        self.assertFalse(main.intrabar_entry_window(1.99))
        self.assertFalse(main.intrabar_entry_window(10.0))


class AssetDiscoveryTests(unittest.TestCase):
    def test_market_assets_do_not_request_or_filter_payout(self):
        connector = Mock()
        connector.get_assets.return_value = [
            {"symbol": "EURUSD-OTC", "active_id": 1},
            {"symbol": "EURUSD", "active_id": 2},
            {"symbol": "GBPUSD-OTC", "active_id": 3},
        ]
        assets = main.get_market_assets(connector, {"market_mode": "OTC"})
        self.assertEqual([a["symbol"] for a in assets], ["EURUSD-OTC", "GBPUSD-OTC"])
        connector.get_assets.assert_called_once_with()
        connector.get_payouts.assert_not_called()
        connector.get_open_assets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
