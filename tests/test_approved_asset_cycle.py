import sys
import types
import unittest
from unittest.mock import patch

# The cycle tests exercise local logic only; no live broker client or dotenv is needed.
dotenv_stub = types.ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

bullexapi_stub = types.ModuleType("bullexapi")
stable_api_stub = types.ModuleType("bullexapi.stable_api")
stable_api_stub.Bullex = object
sys.modules.setdefault("bullexapi", bullexapi_stub)
sys.modules.setdefault("bullexapi.stable_api", stable_api_stub)

import main


class FakeConnector:
    def __init__(self, assets=None):
        self.assets = assets or []
        self.candle_requests = []

    def get_open_assets(self, minimum, maximum):
        return list(self.assets)

    def get_candles(self, symbol, seconds, count):
        self.candle_requests.append(symbol)
        return [{"timestamp": i, "open": 1, "close": 1} for i in range(count)]


class ApprovedAssetCycleTests(unittest.TestCase):
    def setUp(self):
        self.previous_assets = list(main._approved_assets)
        main._refresh_stop.clear()

    def tearDown(self):
        with main._approved_lock:
            main._approved_assets = self.previous_assets
        main._refresh_stop.clear()

    def test_empty_new_backtest_preserves_last_valid_approved_list(self):
        previous = [{"symbol": "EURUSD-OTC", "payout_percent": 90,
                     "backtest": {"win_rate": 75}}]
        with main._approved_lock:
            main._approved_assets = previous[:]
        connector = FakeConnector([{"symbol": "GBPUSD-OTC", "payout_percent": 90}])
        settings = {
            "market_mode": "OTC",
            "minimum_payout_percent": 84,
            "maximum_payout_percent": 100,
            "backtest_min_trades": 5,
            "backtest_candles": 100,
        }
        rejected = {"approved": False, "reason": "taxa_abaixo_ou_igual_70",
                    "trades": 10, "wins": 6, "losses": 4, "win_rate": 60}
        with patch.object(main, "evaluate_backtest", return_value=rejected):
            active = main.refresh_approved_assets(connector, settings)
        self.assertEqual(active, previous)
        self.assertEqual(main._approved_assets, previous)

    def test_each_scan_only_visits_the_approved_assets_and_can_repeat(self):
        approved = [
            {"symbol": "EURUSD-OTC", "payout_percent": 90},
            {"symbol": "GBPUSD-OTC", "payout_percent": 91},
        ]
        with main._approved_lock:
            main._approved_assets = approved[:]
        connector = FakeConnector()
        settings = {
            "timeframe": "M1",
            "trade_type": "binary",
            "expiry_minutes": 1,
            "minimum_confidence": 70,
            "scan_interval_seconds": 2,
            "candles_count": 20,
        }
        with patch.object(main, "get_pre_signal", return_value=None):
            with patch.object(main, "analyze", return_value=None):
                self.assertEqual(main.scan_once(connector, settings), [])
                first_pass = list(connector.candle_requests)
                self.assertEqual(main.scan_once(connector, settings), [])
        self.assertEqual(first_pass, ["EURUSD-OTC", "GBPUSD-OTC"])
        self.assertEqual(connector.candle_requests,
                         ["EURUSD-OTC", "GBPUSD-OTC", "EURUSD-OTC", "GBPUSD-OTC"])


if __name__ == "__main__":
    unittest.main()
