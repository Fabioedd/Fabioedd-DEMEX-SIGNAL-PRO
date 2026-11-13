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
    package.stable_api = stable_api

import main


class IntrabarEntryTests(unittest.TestCase):
    SIGNAL_TIMESTAMP = 3540

    def candidate(self):
        return {
            "symbol": "EURUSD-OTC",
            "active_id": 1,
            "direction": "CALL",
            "signal_timestamp": self.SIGNAL_TIMESTAMP,
            "close_timestamp": self.SIGNAL_TIMESTAMP + 60,
            "detected_at_server_timestamp": self.SIGNAL_TIMESTAMP + 0.5,
            "stage": "INTRABAR_SAME_CANDLE",
        }

    def candles(self, current_timestamp=None):
        rows = [
            {
                "timestamp": index * 60,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
            }
            for index in range(60)
        ]
        if current_timestamp is not None:
            rows[-1]["timestamp"] = current_timestamp
        return rows

    def connector(self, rows, server_timestamp):
        class FakeConnector:
            def get_candles(self, symbol, timeframe_seconds, count):
                return rows

            def get_server_timestamp(self):
                return server_timestamp

        return FakeConnector()

    def test_revalidates_signal_while_original_candle_is_open(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(), 3541.5)
        with patch.object(
            main,
            "get_intrabar_signal",
            return_value={"direction": "CALL", "reasons": ["GO 2024"]},
        ):
            result = main.verify_intrabar_signal(connector, {}, candidate)

        self.assertIsNotNone(result)
        self.assertTrue(result["intrabar_signal_verified"])
        self.assertEqual(result["signal_timestamp"], self.SIGNAL_TIMESTAMP)
        self.assertEqual(result["stage"], "INTRABAR_SAME_CANDLE")

    def test_signal_remains_valid_after_five_seconds_while_same_candle_is_open(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(), 3545.51)
        with patch.object(
            main, "get_intrabar_signal", return_value={"direction": "CALL"}
        ):
            result = main.verify_intrabar_signal(connector, {}, candidate)

        # Não existe mais tolerância artificial de 5 segundos:
        # o sinal segue válido enquanto a mesma vela M1 estiver aberta.
        self.assertIsNotNone(result)
        self.assertTrue(result["intrabar_signal_verified"])
        self.assertEqual(result["direction"], "CALL")

    def test_rejects_signal_after_original_candle_closes(self):
        candidate = self.candidate()
        connector = self.connector(
            self.candles(self.SIGNAL_TIMESTAMP + 60),
            self.SIGNAL_TIMESTAMP + 60.1,
        )
        with patch(
            "main.get_intrabar_signal", return_value={"direction": "CALL"}
        ):
            result = main.verify_intrabar_signal(connector, {}, candidate)

        self.assertFalse(result)

    def test_rejects_signal_if_it_disappears(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(), 3541.0)
        with patch.object(main, "get_intrabar_signal", return_value=None):
            result = main.verify_intrabar_signal(connector, {}, candidate)

        self.assertFalse(result)

    def test_rejects_signal_if_direction_changes(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(), 3541.0)
        with patch.object(
            main, "get_intrabar_signal", return_value={"direction": "PUT"}
        ):
            result = main.verify_intrabar_signal(connector, {}, candidate)

        self.assertFalse(result)

    def test_final_order_validation_accepts_only_same_open_candle(self):
        candidate = self.candidate()
        candidate["intrabar_signal_verified"] = True
        connector = self.connector(self.candles(), 3542.0)
        with patch.object(
            main, "get_intrabar_signal", return_value={"direction": "CALL"}
        ):
            valid, reason = main.validate_signal_immediately_before_order(
                connector, {}, candidate
            )

        self.assertTrue(valid)
        self.assertIn("MESMA vela M1", reason)

    def test_final_order_validation_rejects_unverified_candidate(self):
        candidate = self.candidate()
        connector = self.connector(self.candles(), 3542.0)
        valid, reason = main.validate_signal_immediately_before_order(
            connector, {}, candidate
        )

        self.assertFalse(valid)
        self.assertIn("ainda não foi revalidado", reason)

    def test_scan_detects_signal_on_current_forming_candle(self):
        rows = self.candles()
        connector = self.connector(rows, self.SIGNAL_TIMESTAMP + 2.0)
        settings = {
            "timeframe": "M1",
            "trade_type": "binary",
            "candles_count": 60,
        }
        assets = [{"symbol": "EURUSD-OTC", "active_id": 1}]

        with patch.object(
            main,
            "get_intrabar_signal",
            return_value={"direction": "CALL", "reasons": ["GO 2024"]},
        ):
            result = main.scan_once(connector, settings, assets)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["direction"], "CALL")
        self.assertEqual(result[0]["signal_timestamp"], self.SIGNAL_TIMESTAMP)
        self.assertEqual(result[0]["stage"], "INTRABAR_SAME_CANDLE")
        self.assertEqual(
            result[0]["detected_at_server_timestamp"],
            self.SIGNAL_TIMESTAMP + 2.0,
        )

    def test_scan_does_not_use_previous_candle_when_current_candle_is_missing(self):
        rows = self.candles(self.SIGNAL_TIMESTAMP - 60)
        connector = self.connector(rows, self.SIGNAL_TIMESTAMP + 2.0)
        settings = {
            "timeframe": "M1",
            "trade_type": "binary",
            "candles_count": 45,
        }
        assets = [{"symbol": "EURUSD-OTC", "active_id": 1}]

        with patch.object(main, "get_intrabar_signal") as signal:
            result = main.scan_once(connector, settings, assets)

        self.assertEqual(result, [])
        signal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
