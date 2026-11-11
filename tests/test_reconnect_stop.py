import sys
import threading
import types
import unittest
from unittest.mock import patch

# The connector's retry-wait logic does not need the optional broker SDK.
# Stub its import so these unit tests also run in CI without broker packages.
if "bullexapi.stable_api" not in sys.modules:
    package = sys.modules.setdefault("bullexapi", types.ModuleType("bullexapi"))
    stable_api = types.ModuleType("bullexapi.stable_api")
    stable_api.Bullex = object
    package.stable_api = stable_api
    sys.modules["bullexapi.stable_api"] = stable_api

from bullex_connector import BullexReadOnlyConnector


class ReconnectStopTests(unittest.TestCase):
    def test_retry_wait_checks_stop_every_quarter_second(self):
        connector = BullexReadOnlyConnector.__new__(BullexReadOnlyConnector)
        stop_requested = threading.Event()
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            stop_requested.set()

        with patch("bullex_connector.time.sleep", side_effect=fake_sleep):
            with self.assertRaisesRegex(InterruptedError, "Parada solicitada"):
                connector._wait_for_retry(30, stop_requested.is_set)

        self.assertEqual(sleeps, [0.25])

    def test_retry_wait_finishes_when_delay_elapses(self):
        connector = BullexReadOnlyConnector.__new__(BullexReadOnlyConnector)
        with patch("bullex_connector.time.monotonic", side_effect=[10.0, 10.0, 10.3]):
            with patch("bullex_connector.time.sleep") as sleep:
                connector._wait_for_retry(0.2, lambda: False)
        sleep.assert_called_once_with(0.2)

    def test_reconnect_stops_before_another_attempt(self):
        connector = BullexReadOnlyConnector.__new__(BullexReadOnlyConnector)
        with self.assertRaisesRegex(InterruptedError, "Parada solicitada"):
            connector.reconnect_forever(stop_check=lambda: True)


if __name__ == "__main__":
    unittest.main()
