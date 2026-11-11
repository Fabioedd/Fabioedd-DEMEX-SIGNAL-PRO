import sys
import types
import unittest
from unittest.mock import patch

# These tests use a fake connector; no live broker SDK or dotenv is needed.
dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv)
bullexapi = types.ModuleType("bullexapi")
stable_api = types.ModuleType("bullexapi.stable_api")
stable_api.Bullex = object
sys.modules.setdefault("bullexapi", bullexapi)
sys.modules.setdefault("bullexapi.stable_api", stable_api)

import main


class FakeConnector:
    def __init__(self, assets, on_candles=None, error=None):
        self.assets = assets
        self.on_candles = on_candles
        self.error = error

    def get_open_assets(self, minimum, maximum):
        if self.error:
            raise self.error
        return list(self.assets)

    def get_candles(self, symbol, timeframe, count):
        if self.on_candles:
            self.on_candles(symbol)
        return []


class ApprovedAssetRefreshTests(unittest.TestCase):
    def setUp(self):
        main._refresh_stop.clear()
        with main._approved_lock:
            main._approved_assets = [{"symbol": "OLD-OTC"}]

    def tearDown(self):
        main._refresh_stop.clear()
        with main._approved_lock:
            main._approved_assets = []

    def settings(self):
        return {
            "market_mode": "OTC",
            "minimum_payout_percent": 84,
            "maximum_payout_percent": 100,
            "backtest_candles": 100,
        }

    def test_completed_scan_with_no_approved_assets_clears_old_list(self):
        connector = FakeConnector([
            {"symbol": "NEW-OTC", "payout_percent": 90}
        ])
        rejected = {
            "approved": False, "reason": "taxa_abaixo_ou_igual_70",
            "trades": 10, "wins": 7, "losses": 3, "win_rate": 70.0,
        }
        with patch("main.evaluate_backtest", return_value=rejected):
            active = main.refresh_approved_assets(connector, self.settings())

        self.assertEqual(active, [])
        self.assertEqual(main._approved_assets, [])

    def test_interrupted_scan_preserves_previous_approved_list(self):
        def stop_during_scan(symbol):
            main._refresh_stop.set()

        connector = FakeConnector([
            {"symbol": "NEW1-OTC", "payout_percent": 90},
            {"symbol": "NEW2-OTC", "payout_percent": 91},
        ], on_candles=stop_during_scan)
        rejected = {
            "approved": False, "reason": "taxa_abaixo_ou_igual_70",
            "trades": 10, "wins": 6, "losses": 4, "win_rate": 60.0,
        }
        with patch("main.evaluate_backtest", return_value=rejected):
            active = main.refresh_approved_assets(connector, self.settings())

        self.assertEqual(active, [{"symbol": "OLD-OTC"}])
        self.assertEqual(main._approved_assets, [{"symbol": "OLD-OTC"}])

    def test_connection_failure_does_not_replace_previous_list(self):
        connector = FakeConnector([], error=ConnectionError("offline"))

        with self.assertRaises(ConnectionError):
            main.refresh_approved_assets(connector, self.settings())

        self.assertEqual(main._approved_assets, [{"symbol": "OLD-OTC"}])


if __name__ == "__main__":
    unittest.main()
