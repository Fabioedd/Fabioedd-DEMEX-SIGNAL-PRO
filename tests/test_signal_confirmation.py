import sys
import types
import unittest
from unittest.mock import patch

dotenv = sys.modules.setdefault("dotenv", types.ModuleType("dotenv"))
dotenv.load_dotenv = lambda: None

if "bullexapi.stable_api" not in sys.modules:
    package = sys.modules.setdefault("bullexapi", types.ModuleType("bullexapi"))
    package.__path__ = []
    stable_api = types.ModuleType("bullexapi.stable_api")
    stable_api.Bullex = object
    package.stable_api = stable_api
    sys.modules["bullexapi.stable_api"] = stable_api
    expiration = types.ModuleType("bullexapi.expiration")
    expiration.get_expiration_time = lambda timestamp, duration: (int(timestamp // 60 + duration) * 60, 0)
    package.expiration = expiration
    sys.modules["bullexapi.expiration"] = expiration

import main


class ClosedCandleEntryTests(unittest.TestCase):
    CLOSE_TS = 3600.0

    def candles(self, previous_timestamp=3540.0, current_timestamp=3600.0):
        rows = [
            {"timestamp": float(index * 60), "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}
            for index in range(60)
        ]
        rows[-1]["timestamp"] = previous_timestamp
        rows.append({
            "timestamp": current_timestamp, "open": 1.0,
            "high": 1.1, "low": 0.9, "close": 1.0,
        })
        return rows

    def connector(self, rows, server_timestamp):
        class FakeConnector:
            def __init__(self):
                self.calls = 0
            def get_candles(self, symbol, timeframe_seconds, count):
                self.calls += 1
                return rows
            def get_server_timestamp(self):
                return server_timestamp
        return FakeConnector()

    def settings(self):
        return {"timeframe": "M1", "trade_type": "binary", "candles_count": 250}

    def test_signal_at_three_seconds_is_allowed_and_uses_closed_candle(self):
        connector = self.connector(self.candles(), self.CLOSE_TS + 3.0)
        with patch.object(main, "get_signal", return_value={"direction": "CALL", "reasons": ["GO 2024"]}) as signal:
            result = main.scan_once(connector, self.settings(), [{"symbol": "EURUSD-OTC", "active_id": 1}])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["stage"], "CLOSED_CANDLE_N_PLUS_1")
        self.assertEqual(result[0]["signal_timestamp"], 3540.0)
        self.assertEqual(result[0]["entry_open_timestamp"], 3600.0)
        self.assertEqual(result[0]["entry_close_timestamp"], 3660.0)
        signal.assert_called_once()

    def test_signal_after_three_seconds_is_discarded(self):
        connector = self.connector(self.candles(), self.CLOSE_TS + 3.001)
        with patch.object(main, "get_signal") as signal:
            result = main.scan_once(connector, self.settings(), [{"symbol": "EURUSD-OTC", "active_id": 1}])
        self.assertEqual(result, [])
        signal.assert_not_called()

    def test_old_candle_pair_is_rejected(self):
        connector = self.connector(self.candles(previous_timestamp=3480.0), self.CLOSE_TS + 0.5)
        with patch.object(main, "get_signal") as signal:
            result = main.scan_once(connector, self.settings(), [{"symbol": "EURUSD-OTC", "active_id": 1}])
        self.assertEqual(result, [])
        signal.assert_not_called()

    def test_current_candle_must_be_present_to_prove_n_plus_one(self):
        rows = self.candles()
        rows.pop()
        connector = self.connector(rows, self.CLOSE_TS + 0.5)
        with patch.object(main, "get_signal") as signal:
            result = main.scan_once(connector, self.settings(), [{"symbol": "EURUSD-OTC", "active_id": 1}])
        self.assertEqual(result, [])
        signal.assert_not_called()

    def test_closed_signal_revalidation_rejects_entry_after_deadline(self):
        candidate = {
            "symbol": "EURUSD-OTC", "active_id": 1, "direction": "CALL",
            "signal_timestamp": 3540.0, "close_timestamp": 3600.0,
            "entry_deadline_timestamp": 3603.0, "entry_close_timestamp": 3660.0,
        }
        connector = self.connector(self.candles(), 3603.001)
        with patch.object(main, "get_signal", return_value={"direction": "CALL"}):
            self.assertFalse(main.verify_closed_signal(connector, self.settings(), candidate))

    def test_closed_signal_revalidation_rejects_changed_direction(self):
        candidate = {
            "symbol": "EURUSD-OTC", "active_id": 1, "direction": "CALL",
            "signal_timestamp": 3540.0, "close_timestamp": 3600.0,
            "entry_deadline_timestamp": 3603.0, "entry_close_timestamp": 3660.0,
        }
        connector = self.connector(self.candles(), 3600.5)
        with patch.object(main, "get_signal", return_value={"direction": "PUT"}):
            self.assertFalse(main.verify_closed_signal(connector, self.settings(), candidate))


if __name__ == "__main__":
    unittest.main()
