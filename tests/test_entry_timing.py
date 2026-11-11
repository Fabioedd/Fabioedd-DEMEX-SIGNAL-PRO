import unittest
from pathlib import Path

from entry_timing import (
    can_add_pending_signal,
    filter_market_assets,
    is_candle_still_open,
    is_close_confirmation_window,
)


class CandleCloseTests(unittest.TestCase):
    def test_intrabar_signal_waits_for_candle_close(self):
        self.assertTrue(is_candle_still_open(30.0))
        self.assertTrue(is_candle_still_open(0.1))
        self.assertFalse(is_candle_still_open(0.0))
        self.assertFalse(is_candle_still_open(-0.1))
        self.assertFalse(is_candle_still_open(None))

    def test_only_immediate_close_confirmation_is_allowed(self):
        self.assertTrue(is_close_confirmation_window(0.0))
        self.assertTrue(is_close_confirmation_window(0.5))
        self.assertTrue(is_close_confirmation_window(0.75))
        self.assertFalse(is_close_confirmation_window(0.76))
        self.assertFalse(is_close_confirmation_window(5.0))
        self.assertFalse(is_close_confirmation_window(-0.1))


class MainSyntaxTests(unittest.TestCase):
    def test_main_module_compiles_without_importing_broker_dependencies(self):
        source = Path("main.py").read_text(encoding="utf-8")
        compile(source, "main.py", "exec")


class MultiplePendingSignalTests(unittest.TestCase):
    def test_allows_up_to_three_pending_signals(self):
        self.assertTrue(can_add_pending_signal(0))
        self.assertTrue(can_add_pending_signal(1))
        self.assertTrue(can_add_pending_signal(2))
        self.assertFalse(can_add_pending_signal(3))
        self.assertFalse(can_add_pending_signal(4))

    def test_pending_limit_can_be_configured_for_two(self):
        self.assertTrue(can_add_pending_signal(1, 2))
        self.assertFalse(can_add_pending_signal(2, 2))


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
