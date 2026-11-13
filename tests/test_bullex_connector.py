import unittest
from unittest.mock import patch

from bullex_connector import (
    BullexConfig,
    BullexReadOnlyConnector,
    OrderConfirmationUnknownError,
    OrderRejectedError,
)


class FakeApi:
    def __init__(self, response=None, error=None):
        self.buy_multi_option = {}
        self.response = response
        self.error = error
        self.sent = None
        self.get_options_v2_data = None

    def buyv3_by_raw_expired(self, amount, active_id, direction, option, expiry, request_id):
        self.sent = (amount, active_id, direction, option, expiry, request_id)
        if self.error:
            raise self.error
        if self.response is not None:
            self.buy_multi_option[request_id] = dict(self.response)

    def get_options_v2(self, count, instruments):
        self.get_options_v2_data = {
            "msg": {
                "closed_options": [
                    {"id": 456, "win": "win", "amount": 5.0, "win_amount": 9.2}
                ]
            }
        }


class FakeClient:
    def __init__(self, api):
        self.api = api
        self.logout_count = 0

    def connect(self):
        return True, "ok"

    def logout(self):
        self.logout_count += 1

    def check_connect(self):
        return True

    def get_balance_mode(self):
        return "PRACTICE"

    def get_all_ACTIVES_OPCODE(self):
        return {"EURUSD-OTC": 76}

    def get_server_timestamp(self):
        return 1_800_000_000


class BullexConnectorTests(unittest.TestCase):
    def make_connector(self, api):
        client = FakeClient(api)
        with patch("bullex_connector.Bullex", return_value=client):
            connector = BullexReadOnlyConnector(
                BullexConfig("demo@example.com", "not-a-real-password", "PRACTICE")
            )
        connector.connected = True
        return connector, client

    def test_order_uses_broker_expiry_type_without_cross_product_fallback(self):
        api = FakeApi(response={"id": 98765})
        connector, _ = self.make_connector(api)
        with patch("bullex_connector.get_expiration_time", return_value=(1_800_000_060, 0)), patch("bullex_connector.time.monotonic", side_effect=[0.0, 6.0, 10.0, 16.0]), patch("bullex_connector.time.sleep"):
            with self.assertRaises(OrderConfirmationUnknownError) as first:
                connector.place_practice_order("EURUSD-OTC", "CALL", 5.0, 1)
            with self.assertRaises(OrderConfirmationUnknownError) as second:
                connector.place_practice_order("EURUSD-OTC", "PUT", 5.0, 1)

        first_ref = first.exception.request_ref
        second_ref = second.exception.request_ref
        self.assertNotEqual(first_ref["request_id"], second_ref["request_id"])
        self.assertEqual(len(connector.pending_order_requests), 2)
        api.buy_multi_option[first_ref["request_id"]] = {"id": 501}
        api.buy_multi_option[second_ref["request_id"]] = {"id": 502}
        self.assertEqual(connector.read_order_confirmation(first_ref), ("accepted", 501))
        self.assertEqual(connector.read_order_confirmation(second_ref), ("accepted", 502))
        self.assertIs(first_ref["client"], client)

    def test_result_wait_releases_api_lock_while_waiting_for_history(self):
        import threading
        import time

        api = FakeApi()
        api.get_options_v2 = lambda count, instruments: setattr(api, "get_options_v2_data", None)
        connector, _ = self.make_connector(api)
        finished = threading.Event()

        def wait_for_result():
            try:
                connector.wait_practice_result(456, timeout_seconds=0.2)
            except TimeoutError:
                pass
            finally:
                finished.set()

        worker = threading.Thread(target=wait_for_result)
        worker.start()
        time.sleep(0.03)
        acquired = connector.api_lock.acquire(blocking=False)
        if acquired:
            connector.api_lock.release()
        worker.join(timeout=1.0)
        self.assertTrue(acquired, "api_lock deve ficar livre durante a espera da resposta")
        self.assertTrue(finished.is_set())

    def test_result_wait_obeys_global_deadline(self):
        api = FakeApi()
        api.get_options_v2 = lambda count, instruments: setattr(
            api, "get_options_v2_data",
            {"msg": {"closed_options": [{"id": 999, "win": "win", "amount": 5.0, "win_amount": 9.2}]}}
        )
        connector, _ = self.make_connector(api)
        with self.assertRaises(TimeoutError):
            connector.wait_practice_result(456, timeout_seconds=0.05)

    def test_result_wait_can_be_interrupted_by_stop(self):
        api = FakeApi()
        connector, _ = self.make_connector(api)
        with self.assertRaises(InterruptedError):
            connector.wait_practice_result(456, stop_check=lambda: True)

    def test_result_is_retrieved_from_closed_order_history(self):
        api = FakeApi()
        connector, _ = self.make_connector(api)
        result = connector.wait_practice_result(456)
        self.assertEqual(result, ("WIN", 4.2))


if __name__ == "__main__":
    unittest.main()
