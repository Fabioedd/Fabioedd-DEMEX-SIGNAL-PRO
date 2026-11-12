import sys
import types
import unittest
from unittest.mock import patch

# main imports python-dotenv at runtime; provide a no-op for these isolated tests.
dotenv = sys.modules.setdefault("dotenv", types.ModuleType("dotenv"))
dotenv.load_dotenv = lambda: None

# Stub optional broker SDK import: these tests exercise only local signal logic.
if "bullexapi.stable_api" not in sys.modules:
    package = sys.modules.setdefault("bullexapi", types.ModuleType("bullexapi"))
    package.__path__ = []
    stable_api = types.ModuleType("bullexapi.stable_api")
    stable_api.Bullex = object
    package.stable_api = stable_api
    sys.modules["bullexapi.stable_api"] = stable_api

import main


class SignalConfirmationTests(unittest.TestCase):
    def candidate(self):
        return {
            "symbol": "EURUSD-OTC",
            "active_id": 1,
            "direction": "CALL",
            "signal_timestamp": 600,
            "close_timestamp": 660,
            # Simula o payload produzido por verify_closed_signal.
            "closed_signal_verified": True,
            "signal_close_timestamp": 660,
        }

    def candles(self, closed_timestamp):
        rows = [
            {"timestamp": index * 60, "open": 1.0, "high": 1.1,
             "low": 0.9, "close": 1.0}
            for index in range(50)
        ]
        rows[-2]["timestamp"] = closed_timestamp
        rows[-1]["timestamp"] = closed_timestamp + 60
        return rows

    def connector(self, candles, server_timestamp=660):
        class FakeConnector:
            def get_candles(self, symbol, timeframe_seconds, count):
                return candles
            def get_server_timestamp(self):
                return server_timestamp
        return FakeConnector()

    def test_waits_until_the_candidate_candle_is_closed(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(540), server_timestamp=659)
        self.assertIsNone(main.verify_closed_signal(connector, {}, candidate))

    def test_returns_confirmed_signal_for_same_closed_candle(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(600))
        with patch.object(main, "get_signal_at_index", return_value={"direction": "CALL", "rsi": 25.0}):
            result = main.verify_closed_signal(connector, {}, candidate)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["signal_timestamp"], 600)
        self.assertEqual(result["symbol"], "EURUSD-OTC")

    def test_confirms_candidate_when_api_returns_it_as_last_candle(self):
        candidate = self.candidate()
        rows = self.candles(540)
        rows[-1]["timestamp"] = 600
        connector = self.connector(rows)
        with patch.object(main, "get_signal_at_index", return_value={"direction": "CALL"}):
            result = main.verify_closed_signal(connector, {}, candidate)
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["signal_timestamp"], 600)

    def test_rejects_signal_that_disappeared_at_close(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(600))
        with patch.object(main, "get_signal_at_index", return_value=None):
            self.assertFalse(main.verify_closed_signal(connector, {}, candidate))

    def test_rejects_signal_that_changed_direction_at_next_open(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(600))
        with patch.object(main, "get_signal_at_index", return_value={"direction": "PUT"}):
            self.assertFalse(main.verify_closed_signal(connector, {}, candidate))

    def test_rejects_when_the_target_candle_was_missed(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(660))
        self.assertFalse(main.verify_closed_signal(connector, {}, candidate))


    def test_final_validation_allows_order_only_in_first_five_seconds_of_next_candle(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(600), server_timestamp=662)
        with patch.object(main, "get_signal_at_index", return_value={"direction": "CALL"}):
            valid, reason = main.validate_signal_immediately_before_order(
                connector, {}, candidate
            )
        self.assertTrue(valid)
        self.assertIn("mesma vela", reason)

    def test_final_validation_rejects_after_five_second_tolerance(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(600), server_timestamp=665.01)
        with patch.object(main, "get_signal_at_index", return_value={"direction": "CALL"}):
            valid, reason = main.validate_signal_immediately_before_order(
                connector, {}, candidate
            )
        self.assertFalse(valid)
        self.assertIn("tolerância", reason)

    def test_final_validation_rejects_third_candle_even_if_signal_remains(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(600), server_timestamp=720)
        with patch.object(main, "get_signal_at_index", return_value={"direction": "CALL"}):
            valid, reason = main.validate_signal_immediately_before_order(
                connector, {}, candidate
            )
        self.assertFalse(valid)
        self.assertIn("vela imediatamente seguinte", reason)

    def test_scan_returns_only_the_first_closed_signal_without_backtest(self):
        assets = [{"symbol": name + "-OTC", "active_id": i}
                  for i, name in enumerate(["A", "B", "C", "D", "E", "F"], 1)]
        candles = [
            {"timestamp": 600 + i * 60, "open": 1.0, "high": 1.1,
             "low": 0.9, "close": 1.0}
            for i in range(45)
        ]
        class FakeConnector:
            def get_candles(self, symbol, timeframe_seconds, count):
                return candles
            def get_server_timestamp(self):
                return 600 + 44 * 60 + 60 + 2
        with patch.object(main, "get_signal_at_index", return_value={"direction": "CALL"}):
            result = main.scan_once(
                FakeConnector(), {"timeframe": "M1", "trade_type": "binary"},
                assets, max_candidates=5
            )
        self.assertEqual(len(result), 1)
        self.assertEqual([item["symbol"] for item in result],
                         ["A-OTC"])
        self.assertEqual(result[0]["direction"], "CALL")
        self.assertTrue(all("backtest_accuracy" not in item for item in result))
        self.assertFalse(hasattr(main, "backtest_strategy"))




class IntrabarEntryTests(unittest.TestCase):
    def candidate(self):
        return {
            "symbol": "EURUSD-OTC", "active_id": 1, "direction": "CALL",
            "signal_timestamp": 2640, "close_timestamp": 2700,
            "detected_at_server_timestamp": 2640.5, "stage": "INTRABAR_ENTRY",
        }

    def candles(self, current_timestamp=2640):
        rows = [
            {"timestamp": index * 60, "open": 1.0, "high": 1.1,
             "low": 0.9, "close": 1.0}
            for index in range(45)
        ]
        rows[-1]["timestamp"] = current_timestamp
        return rows

    def connector(self, rows, server_timestamp):
        class FakeConnector:
            def get_candles(self, symbol, timeframe_seconds, count):
                return rows
            def get_server_timestamp(self):
                return server_timestamp
        return FakeConnector()

    def test_confirms_signal_while_same_candle_is_still_open(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(), 2641.5)
        with patch.object(main, "get_intrabar_signal", return_value={"direction": "CALL", "reasons": ["GO 2024"]}):
            result = main.verify_intrabar_signal(connector, {}, candidate)
        self.assertTrue(result["intrabar_signal_verified"])
        self.assertEqual(result["signal_timestamp"], 2640)

    def test_rejects_after_five_seconds_from_detection(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(), 2645.51)
        with patch.object(main, "get_intrabar_signal", return_value={"direction": "CALL"}):
            self.assertFalse(main.verify_intrabar_signal(connector, {}, candidate))

    def test_rejects_when_signal_candle_is_no_longer_current(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(2700), 2700.5)
        with patch.object(main, "get_intrabar_signal", return_value={"direction": "CALL"}):
            self.assertFalse(main.verify_intrabar_signal(connector, {}, candidate))

    def test_rejects_if_intrabar_signal_disappears(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(), 2641.0)
        with patch.object(main, "get_intrabar_signal", return_value=None):
            self.assertFalse(main.verify_intrabar_signal(connector, {}, candidate))

    def test_final_validation_allows_order_only_in_next_candle_within_five_seconds(self):
        candidate = self.candidate()
        candidate["intrabar_signal_verified"] = True
        connector = self.connector(self.candles(), 2642.0)
        with patch.object(main, "get_intrabar_signal", return_value={"direction": "CALL"}):
            valid, reason = main.validate_intrabar_signal_immediately_before_order(
                connector, {}, candidate
            )
        self.assertTrue(valid)
        self.assertIn("própria vela", reason)

if __name__ == "__main__":
    unittest.main()
