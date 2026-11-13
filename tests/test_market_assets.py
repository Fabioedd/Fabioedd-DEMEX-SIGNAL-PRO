import unittest
from unittest.mock import patch

from bullex_connector import MarketDataUnavailableError
from main import get_market_assets


class FakeConnector:
    def __init__(self, responses):
        self.responses = list(responses)
        self.connected = True
        self.reconnects = 0
        self.calls = 0
        self.expiries = []

    def get_otc_asset_availability(self, expiry_minutes=1):
        self.calls += 1
        self.expiries.append(expiry_minutes)
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def reconnect_forever(self, stop_check=None):
        self.reconnects += 1
        self.connected = True


class MarketAssetRetryTests(unittest.TestCase):
    def test_retries_incomplete_bullx_response_until_valid_assets_arrive(self):
        valid = [{"symbol": "EURUSD-OTC", "active_id": 76, "available": True}]
        connector = FakeConnector([
            MarketDataUnavailableError("resposta vazia"),
            MarketDataUnavailableError("resposta incompleta"),
            valid,
        ])

        with patch("main._wait_for_market_data_retry") as wait, patch(
            "main.filter_market_assets", side_effect=lambda assets, mode: assets
        ):
            result = get_market_assets(connector, {"market_mode": "OTC"})

        self.assertEqual(result, [{"symbol": "EURUSD-OTC", "active_id": 76}])
        self.assertEqual(connector.calls, 3)
        self.assertEqual(connector.reconnects, 0)
        self.assertEqual(connector.expiries, [1, 1, 1])
        self.assertEqual(
            [call.args[0] for call in wait.call_args_list],
            [5, 10],
        )

    def test_retries_empty_availability_list(self):
        valid = [{"symbol": "EURUSD-OTC", "active_id": 76, "available": True}]
        connector = FakeConnector([[], valid])

        with patch("main._wait_for_market_data_retry") as wait, patch(
            "main.filter_market_assets", side_effect=lambda assets, mode: assets
        ):
            result = get_market_assets(connector, {"market_mode": "OTC"})

        self.assertEqual(len(result), 1)
        self.assertEqual(connector.calls, 2)
        wait.assert_called_once_with(5, stop_check=None)

    def test_stop_request_interrupts_retry_without_scanning(self):
        connector = FakeConnector([
            MarketDataUnavailableError("resposta vazia"),
        ])

        with patch("main._wait_for_market_data_retry", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                get_market_assets(
                    connector,
                    {"market_mode": "OTC"},
                    stop_check=lambda: False,
                )

        self.assertEqual(connector.calls, 1)


if __name__ == "__main__":
    unittest.main()
