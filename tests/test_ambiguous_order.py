import json
import os
import tempfile
import threading
import unittest
import sys
import types

# The connector's external Bullex client is not needed in these isolated tests.
bullexapi_stub = types.ModuleType("bullexapi")
stable_api_stub = types.ModuleType("bullexapi.stable_api")
stable_api_stub.Bullex = object
bullexapi_stub.stable_api = stable_api_stub
sys.modules.setdefault("bullexapi", bullexapi_stub)
sys.modules.setdefault("bullexapi.stable_api", stable_api_stub)

from bullex_connector import BullexReadOnlyConnector


class FakeConfig:
    account_type = "PRACTICE"


class FakeClient:
    def __init__(self, response):
        self.response = response

    def check_connect(self):
        return True

    def get_balance_mode(self):
        return "PRACTICE"

    def buy(self, *args):
        return self.response


class AmbiguousOrderGuardTests(unittest.TestCase):
    def connector(self, response):
        connector = object.__new__(BullexReadOnlyConnector)
        connector.config = FakeConfig()
        connector.client = FakeClient(response)
        connector.connected = True
        connector.api_lock = threading.RLock()
        connector._active_symbols = {"EURUSD-OTC"}
        return connector

    def test_missing_order_id_persists_lock_record(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                connector = self.connector((False, None))
                with self.assertRaisesRegex(RuntimeError, "SUBMISSÃO AMBÍGUA"):
                    connector.place_practice_order("EURUSD-OTC", "CALL", 5, 1)
                with open(".demex_pending_order.json", encoding="utf-8") as file:
                    record = json.load(file)
                self.assertEqual(record["symbol"], "EURUSD-OTC")
                self.assertEqual(record["direction"], "CALL")
                self.assertEqual(record["amount"], 5.0)
                self.assertEqual(record["account_type"], "PRACTICE")
            finally:
                os.chdir(previous)

    def test_explicit_broker_rejection_does_not_create_ambiguous_lock(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                connector = self.connector((False, "asset not available"))
                with self.assertRaisesRegex(RuntimeError, "asset not available"):
                    connector.place_practice_order("EURUSD-OTC", "CALL", 5, 1)
                self.assertFalse(os.path.exists(".demex_pending_order.json"))
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
