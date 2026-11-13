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
        self.pending_order_request = None

    def place_practice_order(self, symbol, direction, amount, expiry):
        self.orders.append((symbol, direction, amount, expiry))
        return len(self.orders)

    def wait_practice_result(self, order_id, stop_check=None, timeout_seconds=None):
        if stop_check and stop_check():
            raise InterruptedError("stop")
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
    def __init__(self, results):
        super().__init__(results)
        self.request_ref = {"client": self.client, "request_id": "original-request"}

    def place_practice_order(self, symbol, direction, amount, expiry):
        self.orders.append((symbol, direction, amount, expiry))
        raise OrderConfirmationUnknownError(
            "timeout sem ID; estado da ordem desconhecido",
            request_ref=self.request_ref,
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

    def signal(self, n=1, symbol="EURUSD-OTC"):
        return {
            "symbol": symbol,
            "direction": "CALL",
            "signal_timestamp": n,
        }

    def trader(self, connector):
        return DemoTrader(connector, self.settings())

    def queue_order(self, trader, signal):
        with patch.object(trader, "_start_unknown_order_monitor"):
            self.assertIsNone(trader.execute_and_settle(signal))

    def test_confirmed_order_is_queued_and_returns_without_waiting(self):
        c = FakeConnector([("WIN", 4.25)])
        t = self.trader(c)
        self.queue_order(t, self.signal())
        self.assertTrue(t.has_pending_orders)
        self.assertEqual(t.total_entries, 0)
        self.assertEqual(len(c.orders), 1)

        t._monitor_unknown_order()
        self.assertFalse(t.has_pending_orders)
        self.assertEqual(t.total_entries, 1)
        self.assertEqual(t.wins, 1)
        self.assertEqual(t.net, 4.25)

    def test_multiple_orders_continue_and_settle_in_submission_order(self):
        c = FakeConnector([("WIN", 4.25), ("LOSS", -9.25)])
        t = self.trader(c)
        self.queue_order(t, self.signal(1))
        self.queue_order(t, self.signal(2, "GBPUSD-OTC"))

        self.assertEqual(len(c.orders), 2)
        self.assertEqual(len(t.pending_unknown_order_queue), 2)
        self.assertFalse(t.paused)
        t._monitor_unknown_order()

        self.assertFalse(t.has_pending_orders)
        self.assertEqual(t.total_entries, 2)
        self.assertEqual(t.wins, 1)
        self.assertEqual(t.losses, 1)
        self.assertEqual(t.net, -5.0)
        # A WIN followed by LOSS preserves the original Soros sequence.
        self.assertEqual(t.next_entry, t.base)

    def test_unknown_confirmation_does_not_pause_scanner_or_block_next_order(self):
        c = UnknownOrderConnector([])
        t = self.trader(c)
        with patch.object(t, "_start_unknown_order_monitor"):
            with self.assertRaises(OrderConfirmationUnknownError):
                t.execute_and_settle(self.signal(1))
        self.assertFalse(t.paused)
        self.assertFalse(t.stopped)
        self.assertTrue(t.has_pending_orders)

        # Another signal can be submitted while the first request is unresolved.
        c.place_practice_order = FakeConnector.place_practice_order.__get__(c, FakeConnector)
        self.queue_order(t, self.signal(2, "GBPUSD-OTC"))
        self.assertEqual(len(c.orders), 2)

    def test_confirmed_order_stays_ahead_of_later_unknown_confirmation(self):
        c = FakeConnector([("WIN", 4.25), ("LOSS", -5.0)])
        original_place = c.place_practice_order
        calls = {"count": 0}
        request_ref = {"client": c.client, "request_id": "later-request"}

        def place_with_later_unknown(symbol, direction, amount, expiry):
            calls["count"] += 1
            if calls["count"] == 1:
                return original_place(symbol, direction, amount, expiry)
            c.orders.append((symbol, direction, amount, expiry))
            raise OrderConfirmationUnknownError(
                "late confirmation", request_ref=request_ref
            )

        c.place_practice_order = place_with_later_unknown
        t = self.trader(c)
        with patch.object(t, "_start_unknown_order_monitor"):
            self.assertIsNone(t.execute_and_settle(self.signal(1)))
            with self.assertRaises(OrderConfirmationUnknownError):
                t.execute_and_settle(self.signal(2, "GBPUSD-OTC"))

        self.assertIsNone(t.pending_unknown_order)
        self.assertEqual(len(t.pending_unknown_order_queue), 2)
        c.client.api.buy_multi_option["later-request"] = {"id": 2}
        t._monitor_unknown_order()

        self.assertFalse(t.has_pending_orders)
        self.assertEqual(t.total_entries, 2)
        self.assertEqual(t.wins, 1)
        self.assertEqual(t.losses, 1)
        self.assertEqual(t.net, -0.75)

    def test_late_confirmation_is_reconciled_without_resending(self):
        c = UnknownOrderConnector([("WIN", 4.25)])
        c.client.api.buy_multi_option["original-request"] = {"id": 987654}
        t = self.trader(c)
        with patch.object(t, "_start_unknown_order_monitor"):
            with self.assertRaises(OrderConfirmationUnknownError):
                t.execute_and_settle(self.signal())
        t._monitor_unknown_order()
        self.assertFalse(t.has_pending_orders)
        self.assertEqual(t.total_entries, 1)
        self.assertEqual(t.net, 4.25)
        self.assertEqual(len(c.orders), 1)

    def test_late_explicit_rejection_does_not_count_entry(self):
        c = UnknownOrderConnector([])
        c.client.api.buy_multi_option["original-request"] = {"message": "order rejected"}
        t = self.trader(c)
        with patch.object(t, "_start_unknown_order_monitor"):
            with self.assertRaises(OrderConfirmationUnknownError):
                t.execute_and_settle(self.signal())
        t._monitor_unknown_order()
        self.assertFalse(t.has_pending_orders)
        self.assertEqual(t.total_entries, 0)
        self.assertEqual(t.net, 0)

    def test_take_profit_stops_new_entries_but_monitor_finishes_existing_queue(self):
        c = FakeConnector([("WIN", 50.0), ("LOSS", -5.0)])
        t = self.trader(c)
        self.queue_order(t, self.signal(1))
        self.queue_order(t, self.signal(2, "GBPUSD-OTC"))
        t._monitor_unknown_order()

        self.assertTrue(t.stopped)
        self.assertEqual(t.stop_reason, "TAKE PROFIT atingido")
        self.assertFalse(t.has_pending_orders)
        self.assertEqual(t.total_entries, 2)
        self.assertIsNone(t.execute_and_settle(self.signal(3)))

    def test_stop_loss_stops_new_entries(self):
        c = FakeConnector([("LOSS", -5.0), ("LOSS", -5.0), ("LOSS", -5.0)])
        t = self.trader(c)
        for n in (1, 2, 3):
            self.queue_order(t, self.signal(n, "ASSET{}".format(n)))
        t._monitor_unknown_order()
        self.assertTrue(t.stopped)
        self.assertEqual(t.net, -15.0)
        self.assertIsNone(t.execute_and_settle(self.signal(4)))

    def test_soros_one_then_reset_after_background_results(self):
        c = FakeConnector([("WIN", 4.25), ("WIN", 7.86)])
        t = self.trader(c)
        self.queue_order(t, self.signal(1))
        t._monitor_unknown_order()
        self.assertEqual(t.next_entry, 9.25)
        self.queue_order(t, self.signal(2))
        t._monitor_unknown_order()
        self.assertEqual(t.next_entry, 5.0)

    def test_duplicate_signal_is_ignored(self):
        c = FakeConnector([("WIN", 4.25)])
        t = self.trader(c)
        self.queue_order(t, self.signal(1))
        self.assertIsNone(t.execute_and_settle(self.signal(1)))
        self.assertEqual(len(c.orders), 1)

    def test_stop_interrupts_before_order_submission(self):
        c = FakeConnector([])
        t = DemoTrader(c, self.settings(), stop_check=lambda: True)
        with self.assertRaises(InterruptedError):
            t.execute_and_settle(self.signal())
        self.assertEqual(len(c.orders), 0)
        self.assertFalse(t.busy)


if __name__ == "__main__":
    unittest.main()
