import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bullex_connector import OrderConfirmationUnknownError
from trade_manager import DemoTrader


class FakeClient:
    def __init__(self):
        self.api = SimpleNamespace(buy_multi_option={})

    def get_balance_mode(self):
        return "PRACTICE"


class FakeConnector:
    class Config:
        account_type = "PRACTICE"

    config = Config()

    def __init__(self, results):
        self.results = list(results)
        self.orders = []
        self.reconnects = 0
        self.connected = True
        self.client = FakeClient()

    def place_practice_order(self, symbol, direction, amount, expiry):
        self.orders.append((symbol, direction, amount, expiry))
        return len(self.orders)

    def wait_practice_result(self, order_id):
        item = self.results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def reconnect_forever(self, stop_check=None):
        if stop_check and stop_check():
            raise InterruptedError("stop")
        self.reconnects += 1
        self.connected = True
        return True

    def read_order_confirmation(self, request_ref):
        client = request_ref["client"]
        request_id = request_ref["request_id"]
        payload = client.api.buy_multi_option.get(request_id)
        if not isinstance(payload, dict):
            return "pending", None
        if payload.get("id") is not None:
            return "accepted", int(payload["id"])
        if payload.get("message"):
            return "rejected", str(payload["message"])
        return "pending", None

    def clear_pending_order_request(self, request_ref=None):
        return None


class UnknownOrderConnector(FakeConnector):
    def place_practice_order(self, symbol, direction, amount, expiry):
        self.orders.append((symbol, direction, amount, expiry))
        raise OrderConfirmationUnknownError(
            "timeout sem ID; estado da ordem desconhecido"
        )


class TradeManagerTests(unittest.TestCase):
    def settings(self):
        return {
            "expiry_minutes": 1,
            "trading": {
                "initial_entry_brl": 5,
                "stop_loss_brl": 15,
                "take_profit_brl": 50,
            },
        }

    def signal(self, n=1):
        return {
            "symbol": "EURUSD-OTC",
            "direction": "CALL",
            "signal_timestamp": n,
        }

    def test_soros_one_then_reset(self):
        c = FakeConnector([("WIN", 4.25), ("WIN", 7.86)])
        t = DemoTrader(c, self.settings())
        a = t.execute_and_settle(self.signal(1))
        self.assertEqual(a["entry"], 5.0)
        self.assertEqual(a["next_entry"], 9.25)
        b = t.execute_and_settle(self.signal(2))
        self.assertEqual(b["entry"], 9.25)
        self.assertEqual(b["next_entry"], 5.0)

    def test_loss_resets_entry(self):
        c = FakeConnector([("LOSS", -5.0)])
        t = DemoTrader(c, self.settings())
        r = t.execute_and_settle(self.signal())
        self.assertEqual(r["next_entry"], 5.0)
        self.assertEqual(r["session_net"], -5.0)

    def test_stop_loss_stops_session(self):
        c = FakeConnector([("LOSS", -5.0), ("LOSS", -5.0), ("LOSS", -5.0)])
        t = DemoTrader(c, self.settings())
        t.execute_and_settle(self.signal(1))
        t.execute_and_settle(self.signal(2))
        r = t.execute_and_settle(self.signal(3))
        self.assertTrue(r["stopped"])
        self.assertEqual(r["session_net"], -15.0)
        self.assertIsNone(t.execute_and_settle(self.signal(4)))

    def test_errno_103_reconnects_and_checks_same_order_without_duplicate(self):
        c = FakeConnector([
            ConnectionAbortedError(103, "Software caused connection abort"),
            ("WIN", 4.25),
        ])
        t = DemoTrader(c, self.settings())
        r = t.execute_and_settle(self.signal())
        self.assertEqual(r["result"], "WIN")
        self.assertEqual(c.reconnects, 1)
        self.assertEqual(len(c.orders), 1)
        self.assertEqual(t.total_entries, 1)

    def test_unexpected_result_response_reconnects_and_rechecks_same_order(self):
        c = FakeConnector([
            ValueError("resposta inesperada da corretora"),
            ("WIN", 4.25),
        ])
        t = DemoTrader(c, self.settings())
        r = t.execute_and_settle(self.signal())
        self.assertEqual(r["result"], "WIN")
        self.assertEqual(c.reconnects, 1)
        self.assertEqual(len(c.orders), 1)
        self.assertEqual(t.total_entries, 1)

    def test_late_order_lookup_ignores_unrelated_request_ids(self):
        c = FakeConnector([])
        c.client.api.buy_multi_option = {"other-request": {"id": 12345}}
        t = DemoTrader(c, self.settings())
        t.pending_unknown_order = {
            "signal": self.signal(1),
            "amount": t.base,
            "request_ref": {"client": c.client, "request_id": "original-request"},
        }
        self.assertEqual(t._read_late_order_response(), ("pending", None))

    def test_win_and_loss_streaks_are_tracked_and_tie_resets_them(self):
        c = FakeConnector([("WIN", 4.25), ("WIN", 4.25), ("LOSS", -5.0), ("TIE", 0.0)])
        t = DemoTrader(c, self.settings())
        first = t.execute_and_settle(self.signal(1))
        second = t.execute_and_settle(self.signal(2))
        third = t.execute_and_settle(self.signal(3))
        fourth = t.execute_and_settle(self.signal(4))
        self.assertEqual(first["current_win_streak"], 1)
        self.assertEqual(second["max_win_streak"], 2)
        self.assertEqual(third["current_loss_streak"], 1)
        self.assertEqual(fourth["current_win_streak"], 0)
        self.assertEqual(fourth["current_loss_streak"], 0)
        self.assertEqual(fourth["max_win_streak"], 2)
        self.assertEqual(fourth["max_loss_streak"], 1)

    def test_take_profit_stops_session(self):
        c = FakeConnector([("WIN", 50.0)])
        t = DemoTrader(c, self.settings())
        r = t.execute_and_settle(self.signal())
        self.assertTrue(r["stopped"])
        self.assertEqual(r["session_net"], 50.0)

    def test_unknown_confirmation_keeps_process_alive_and_blocks_new_orders(self):
        c = UnknownOrderConnector([])
        t = DemoTrader(c, self.settings())
        with patch.object(t, "_start_unknown_order_monitor"):
            with self.assertRaises(OrderConfirmationUnknownError):
                t.execute_and_settle(self.signal(1))

        self.assertTrue(t.paused)
        self.assertFalse(t.stopped)
        # main.py's legacy catch still assigns stopped=True; the setter
        # intentionally converts that into a recoverable pause.
        t.stopped = True
        self.assertFalse(t.stopped)
        self.assertIsNone(t.execute_and_settle(self.signal(2)))
        self.assertEqual(len(c.orders), 1)
        self.assertEqual(t.total_entries, 0)

    def test_late_order_id_is_reconciled_and_session_resumes(self):
        c = FakeConnector([("WIN", 4.25)])
        c.client.api.buy_multi_option = {"original-request": {"id": 987654}}
        t = DemoTrader(c, self.settings())
        t.paused = True
        t.pending_unknown_order = {
            "signal": self.signal(1),
            "amount": t.base,
            "submitted_at": 123.0,
            "reason": "initial timeout",
            "request_ref": {"client": c.client, "request_id": "original-request"},
        }
        late_notifications = []
        t.late_settlement_callback = late_notifications.append

        t._monitor_unknown_order()

        self.assertFalse(t.paused)
        self.assertIsNone(t.pending_unknown_order)
        self.assertEqual(t.total_entries, 1)
        self.assertEqual(t.wins, 1)
        self.assertEqual(t.net, 4.25)
        self.assertEqual(len(c.orders), 0)
        self.assertEqual(len(late_notifications), 1)
        self.assertEqual(late_notifications[0]["result"], "WIN")

    def test_late_explicit_rejection_resumes_without_counting_entry(self):
        c = FakeConnector([])
        c.client.api.buy_multi_option = {
            "original-request": {"message": "order rejected"}
        }
        t = DemoTrader(c, self.settings())
        t.paused = True
        t.pending_unknown_order = {
            "signal": self.signal(1),
            "amount": t.base,
            "submitted_at": 123.0,
            "reason": "initial timeout",
            "request_ref": {"client": c.client, "request_id": "original-request"},
        }

        t._monitor_unknown_order()

        self.assertFalse(t.paused)
        self.assertIsNone(t.pending_unknown_order)
        self.assertEqual(t.total_entries, 0)
        self.assertEqual(t.net, 0)


if __name__ == "__main__":
    unittest.main()
