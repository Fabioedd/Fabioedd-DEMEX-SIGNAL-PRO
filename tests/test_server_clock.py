import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bullex_connector import BullexReadOnlyConnector


class ServerClockTests(unittest.TestCase):
    def connector(self, raw_timestamp):
        connector = object.__new__(BullexReadOnlyConnector)
        connector.api_lock = threading.RLock()
        connector.connected = True
        connector.client = SimpleNamespace(
            get_server_timestamp=lambda: raw_timestamp,
            check_connect=lambda: True,
        )
        connector._server_clock_anchor_timestamp = None
        connector._server_clock_anchor_monotonic_ns = None
        connector._server_clock_last_raw = None
        return connector

    def test_server_clock_advances_from_monotonic_time_when_timesync_is_unchanged(self):
        connector = self.connector(1_800_000_000.0)
        with patch("bullex_connector.time.monotonic_ns", side_effect=[1_000_000_000, 1_250_000_000]):
            first = connector.get_server_timestamp()
            second = connector.get_server_timestamp()
        self.assertEqual(first, 1_800_000_000.0)
        self.assertAlmostEqual(second, 1_800_000_000.25)

    def test_server_clock_rejects_uninitialized_timesync_value(self):
        connector = self.connector(1_800_000.0)
        with self.assertRaises(RuntimeError):
            connector.get_server_timestamp()

    def test_server_clock_rejects_stale_timesync_anchor(self):
        connector = self.connector(1_800_000_000.0)
        with patch("bullex_connector.time.monotonic_ns", side_effect=[1_000_000_000, 32_000_000_001]):
            connector.get_server_timestamp()
            with self.assertRaises(RuntimeError):
                connector.get_server_timestamp()



    def test_delayed_timesync_message_never_moves_server_clock_backwards(self):
        connector = self.connector(1_800_000_000.0)
        with patch("bullex_connector.time.monotonic_ns", side_effect=[1_000_000_000, 2_000_000_000, 3_000_000_000]):
            first = connector.get_server_timestamp()
            # Uma atualização do WebSocket pode chegar atrasada em relação ao
            # horário já extrapolado pelo relógio monotônico.
            connector.client.get_server_timestamp = lambda: 1_800_000_000.5
            second = connector.get_server_timestamp()
            third = connector.get_server_timestamp()
        self.assertEqual(first, 1_800_000_000.0)
        self.assertAlmostEqual(second, 1_800_000_001.0)
        self.assertAlmostEqual(third, 1_800_000_002.0)

if __name__ == "__main__":
    unittest.main()
