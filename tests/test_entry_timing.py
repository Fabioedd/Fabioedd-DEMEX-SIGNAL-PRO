import unittest
from pathlib import Path

from entry_timing import (
    can_add_pending_signal,
    filter_market_assets,
    is_binary_active_open,
    is_candle_still_open,
    is_close_confirmation_tolerance,
    is_close_confirmation_window,
    is_next_candle_entry_window,
)


class CandleEntryTimingTests(unittest.TestCase):
    def test_signal_candle_must_still_be_open_to_be_queued(self):
        self.assertTrue(is_candle_still_open(30.0))
        self.assertTrue(is_candle_still_open(0.1))
        self.assertFalse(is_candle_still_open(0.0))
        self.assertFalse(is_candle_still_open(-0.1))
        self.assertFalse(is_candle_still_open(None))

    def test_three_seconds_are_confirmation_tolerance_not_a_wait_period(self):
        self.assertTrue(is_close_confirmation_tolerance(0.0))
        self.assertTrue(is_close_confirmation_tolerance(0.05))
        self.assertTrue(is_close_confirmation_tolerance(0.5))
        self.assertTrue(is_close_confirmation_tolerance(2.0))
        self.assertTrue(is_close_confirmation_tolerance(3.0))
        self.assertFalse(is_close_confirmation_tolerance(3.01))
        self.assertFalse(is_close_confirmation_tolerance(5.0))
        self.assertFalse(is_close_confirmation_tolerance(-0.1))
        self.assertFalse(is_close_confirmation_tolerance(None))
        # A função antiga continua disponível para compatibilidade.
        self.assertTrue(is_close_confirmation_window(1.0))

    def test_entry_is_allowed_only_at_start_of_immediately_following_candle(self):
        self.assertTrue(is_next_candle_entry_window(0.0))
        self.assertTrue(is_next_candle_entry_window(0.5))
        self.assertTrue(is_next_candle_entry_window(3.0))
        self.assertTrue(is_next_candle_entry_window(5.0, 5.0, 60.0))
        self.assertFalse(is_next_candle_entry_window(5.01, 5.0, 60.0))
        self.assertFalse(is_next_candle_entry_window(-0.01))
        self.assertFalse(is_next_candle_entry_window(3.01))
        self.assertFalse(is_next_candle_entry_window(59.99))
        self.assertFalse(is_next_candle_entry_window(60.0))
        self.assertFalse(is_next_candle_entry_window(60.01))
        self.assertFalse(is_next_candle_entry_window(None))

    def test_pending_signal_limit(self):
        self.assertTrue(can_add_pending_signal(0))
        self.assertTrue(can_add_pending_signal(1))
        self.assertFalse(can_add_pending_signal(2))
        self.assertFalse(can_add_pending_signal(3))
        self.assertTrue(can_add_pending_signal(1, 2))
        self.assertFalse(can_add_pending_signal(2, 2))


class AssetAvailabilityTests(unittest.TestCase):
    def test_binary_asset_requires_enabled_and_not_suspended(self):
        self.assertTrue(is_binary_active_open({"enabled": True, "is_suspended": False}, 100))
        self.assertFalse(is_binary_active_open({"enabled": False, "is_suspended": False}, 100))
        self.assertFalse(is_binary_active_open({"enabled": True, "is_suspended": True}, 100))

    def test_string_flags_are_interpreted_safely(self):
        self.assertTrue(is_binary_active_open({"enabled": "1", "is_suspended": "0"}, 100))
        self.assertFalse(is_binary_active_open({"enabled": "0", "is_suspended": "0"}, 100))
        self.assertFalse(is_binary_active_open({"enabled": "1", "is_suspended": "1"}, 100))

    def test_binary_asset_schedule_controls_open_state(self):
        active = {"enabled": True, "is_suspended": False, "schedule": [{"open": 100, "close": 200}]}
        self.assertTrue(is_binary_active_open(active, 150))
        self.assertFalse(is_binary_active_open(active, 99))
        self.assertFalse(is_binary_active_open(active, 201))

    def test_binary_asset_supports_pair_schedule_format(self):
        active = {"enabled": True, "is_suspended": False, "schedule": [[100, 200]]}
        self.assertTrue(is_binary_active_open(active, 150))

    def test_malformed_present_schedule_fails_closed(self):
        active = {"enabled": True, "is_suspended": False, "schedule": [{"unexpected": 1}]}
        self.assertFalse(is_binary_active_open(active, 150))


class SyntaxTests(unittest.TestCase):
    def test_main_and_connector_compile_without_connecting_to_broker(self):
        for filename in ("main.py", "bullex_connector.py"):
            source = Path(filename).read_text(encoding="utf-8")
            compile(source, filename, "exec")


class AssetDiscoveryTests(unittest.TestCase):
    def test_market_selection_filters_only_otc_and_never_payout(self):
        assets = [
            {"symbol": "EURUSD-OTC", "active_id": 1, "payout_percent": 5},
            {"symbol": "EURUSD", "active_id": 2, "payout_percent": 100},
            {"symbol": "GBPUSD-OTC", "active_id": 3},
        ]
        selected = filter_market_assets(assets, "OTC")
        self.assertEqual([a["symbol"] for a in selected], ["EURUSD-OTC", "GBPUSD-OTC"])


if __name__ == "__main__":
    unittest.main()
