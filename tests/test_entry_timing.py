import unittest
from pathlib import Path

from entry_timing import (
    can_add_pending_signal,
    filter_market_assets,
    is_candle_still_open,
    is_close_confirmation_window,
    is_intrabar_entry,
)


class ImmediateEntryTests(unittest.TestCase):
    def test_only_current_forming_candle_signal_authorizes_immediate_entry(self):
        self.assertTrue(is_intrabar_entry("INTRABAR"))
        self.assertTrue(is_intrabar_entry("intrabar"))
        self.assertFalse(is_intrabar_entry("CLOSED"))
        self.assertFalse(is_intrabar_entry(None))

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


class AssetAvailabilityTests(unittest.TestCase):
    def test_binary_asset_requires_enabled_and_not_suspended(self):
        from entry_timing import is_binary_active_open
        self.assertTrue(is_binary_active_open({"enabled": True, "is_suspended": False}, 100))
        self.assertFalse(is_binary_active_open({"enabled": False, "is_suspended": False}, 100))
        self.assertFalse(is_binary_active_open({"enabled": True, "is_suspended": True}, 100))

    def test_binary_asset_schedule_controls_open_state(self):
        from entry_timing import is_binary_active_open
        active = {"enabled": True, "is_suspended": False, "schedule": [{"open": 100, "close": 200}]}
        self.assertTrue(is_binary_active_open(active, 150))
        self.assertFalse(is_binary_active_open(active, 99))
        self.assertFalse(is_binary_active_open(active, 201))

    def test_binary_asset_supports_pair_schedule_format(self):
        from entry_timing import is_binary_active_open
        active = {"enabled": True, "is_suspended": False, "schedule": [[100, 200]]}
        self.assertTrue(is_binary_active_open(active, 150))


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


class StrategySignalTests(unittest.TestCase):
    @staticmethod
    def make_candles(direction):
        candles = []
        for i in range(15):
            if direction == "PUT":
                open_price = 100.0 + i
                close_price = open_price + 1.0
                candles.append({
                    "timestamp": i * 60,
                    "open": open_price,
                    "high": close_price + 0.5,
                    "low": open_price - 0.5,
                    "close": close_price,
                })
            else:
                open_price = 115.0 - i
                close_price = open_price - 1.0
                candles.append({
                    "timestamp": i * 60,
                    "open": open_price,
                    "high": open_price + 0.5,
                    "low": close_price - 0.5,
                    "close": close_price,
                })
        if direction == "PUT":
            candles.append({
                "timestamp": 900, "open": 114.0, "high": 115.5,
                "low": 113.5, "close": 115.0,
            })
        else:
            candles.append({
                "timestamp": 900, "open": 100.0, "high": 100.6,
                "low": 98.9, "close": 99.0,
            })
        return candles

    def test_green_candle_touching_previous_m15_high_with_overbought_rsi_is_put(self):
        from strategies.my_strategy import get_intrabar_signal
        signal = get_intrabar_signal(self.make_candles("PUT"), {
            "rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30,
        })
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "PUT")
        self.assertEqual(signal["stage"], "INTRABAR")
        self.assertGreaterEqual(signal["rsi"], 70)

    def test_red_candle_touching_previous_m15_low_with_oversold_rsi_is_call(self):
        from strategies.my_strategy import get_intrabar_signal
        signal = get_intrabar_signal(self.make_candles("CALL"), {
            "rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30,
        })
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "CALL")
        self.assertEqual(signal["stage"], "INTRABAR")
        self.assertLessEqual(signal["rsi"], 30)


if __name__ == "__main__":
    unittest.main()
