import sys
import types
import unittest

# Keep the tests independent from live broker SDK and dotenv installation.
dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv)
bullexapi = types.ModuleType("bullexapi")
stable_api = types.ModuleType("bullexapi.stable_api")
stable_api.Bullex = object
sys.modules.setdefault("bullexapi", bullexapi)
sys.modules.setdefault("bullexapi.stable_api", stable_api)

import main


class FakeClock:
    def __init__(self, timestamp):
        self.timestamp = timestamp

    def get_server_timestamp(self):
        return self.timestamp


class ClosedCandleConfirmationTests(unittest.TestCase):
    def test_entry_allowed_at_candle_open(self):
        signal = {"symbol": "EURUSD-OTC", "signal_timestamp": 1000}
        self.assertTrue(main.signal_is_in_next_candle(
            FakeClock(1060), signal, {"entry_confirmation_window_seconds": 10}
        ))

    def test_entry_allowed_through_nine_point_nine_nine_nine_seconds(self):
        signal = {"symbol": "EURUSD-OTC", "signal_timestamp": 1000}
        self.assertTrue(main.signal_is_in_next_candle(
            FakeClock(1069.999), signal, {"entry_confirmation_window_seconds": 10}
        ))

    def test_entry_rejected_at_ten_seconds_after_candle_open(self):
        signal = {"symbol": "EURUSD-OTC", "signal_timestamp": 1000}
        self.assertFalse(main.signal_is_in_next_candle(
            FakeClock(1070), signal, {"entry_confirmation_window_seconds": 10}
        ))

    def test_entry_rejected_before_next_candle(self):
        signal = {"symbol": "EURUSD-OTC", "signal_timestamp": 1000}
        self.assertFalse(main.signal_is_in_next_candle(
            FakeClock(1059.999), signal, {"entry_confirmation_window_seconds": 10}
        ))

    def test_intrabar_signal_is_confirmed_only_if_same_direction_closes(self):
        pending = {"EURUSD-OTC": {"timestamp": 1000, "direction": "CALL"}}
        closed = {"direction": "CALL", "confidence": 100}
        result = main.resolve_intrabar_confirmation(pending, "EURUSD-OTC", 1000, closed)
        self.assertEqual(result, closed)
        self.assertNotIn("EURUSD-OTC", pending)

    def test_intrabar_signal_that_disappears_is_cancelled(self):
        pending = {"EURUSD-OTC": {"timestamp": 1000, "direction": "CALL"}}
        result = main.resolve_intrabar_confirmation(pending, "EURUSD-OTC", 1000, None)
        self.assertIsNone(result)
        self.assertNotIn("EURUSD-OTC", pending)

    def test_intrabar_signal_that_changes_direction_is_cancelled(self):
        pending = {"EURUSD-OTC": {"timestamp": 1000, "direction": "CALL"}}
        result = main.resolve_intrabar_confirmation(
            pending, "EURUSD-OTC", 1000, {"direction": "PUT"}
        )
        self.assertIsNone(result)
        self.assertNotIn("EURUSD-OTC", pending)

    def test_late_signal_without_intrabar_record_can_still_be_confirmed(self):
        result = {"direction": "PUT", "confidence": 100}
        self.assertEqual(
            main.resolve_intrabar_confirmation({}, "EURUSD-OTC", 1000, result),
            result,
        )


if __name__ == "__main__":
    unittest.main()
