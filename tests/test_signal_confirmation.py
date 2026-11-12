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
        }

    def candles(self, closed_timestamp):
        rows = [
            {"timestamp": index * 60, "open": 1.0, "high": 1.1,
             "low": 0.9, "close": 1.0}
            for index in range(25)
        ]
        rows[-2]["timestamp"] = closed_timestamp
        rows[-1]["timestamp"] = closed_timestamp + 60
        return rows

    def connector(self, candles):
        class FakeConnector:
            def get_candles(self, symbol, timeframe_seconds, count):
                return candles
        return FakeConnector()

    def test_waits_until_the_candidate_candle_is_closed(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(540))
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


    def test_scan_returns_only_the_first_live_signal_without_backtest(self):
        assets = [{"symbol": name + "-OTC", "active_id": i}
                  for i, name in enumerate(["A", "B", "C", "D", "E", "F"], 1)]
        candles = [
            {"timestamp": 600 + i * 60, "open": 1.0, "high": 1.1,
             "low": 0.9, "close": 1.0}
            for i in range(25)
        ]
        class FakeConnector:
            def get_candles(self, symbol, timeframe_seconds, count):
                return candles
            def get_server_timestamp(self):
                return 600 + 24 * 60 + 50
        with patch.object(main, "get_intrabar_signal", return_value={"direction": "CALL"}):
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



if __name__ == "__main__":
    unittest.main()
