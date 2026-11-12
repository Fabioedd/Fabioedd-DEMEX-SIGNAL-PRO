import unittest
from unittest.mock import patch

from asset_selector import backtest_asset, select_qualified_assets


class FakeConnector:
    def __init__(self, candles):
        self.candles = candles
        self.requested_count = None

    def get_candles(self, symbol, timeframe, count):
        self.requested_count = count
        return self.candles

    def get_server_timestamp(self):
        return 260 * 60 + 60


def make_candles(count=260):
    return [
        {
            "timestamp": index * 60,
            "open": 100.0 + index,
            "high": 102.0 + index,
            "low": 99.0 + index,
            "close": 101.0 + index,
        }
        for index in range(count)
    ]


class AssetSelectorTests(unittest.TestCase):
    def test_backtest_uses_200_closed_candles_and_next_candle_result(self):
        candles = make_candles()
        connector = FakeConnector(candles)
        asset = {"symbol": "EURUSD-OTC", "active_id": 76}
        settings = {"backtest_candles_count": 200, "backtest_warmup_candles": 60}

        with patch("asset_selector.get_signal_at_index") as signal:
            signal.side_effect = [
                {"direction": "CALL"},
                {"direction": "PUT"},
                None,
            ] + [None] * 196
            result = backtest_asset(connector, asset, settings)

        self.assertEqual(connector.requested_count, 265)
        self.assertEqual(result["candles_used"], 200)
        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["losses"], 1)
        self.assertEqual(result["operations"], 3)
        self.assertAlmostEqual(result["accuracy"], 200 / 3)
        self.assertFalse(result["approved"])

    def test_exactly_70_percent_is_approved_without_minimum_trade_count(self):
        candles = make_candles()
        connector = FakeConnector(candles)
        asset = {"symbol": "GBPUSD-OTC", "active_id": 77}
        settings = {"minimum_backtest_accuracy": 70}

        with patch("asset_selector.get_signal_at_index") as signal:
            signal.side_effect = [{"direction": "CALL"}] * 10 + [None] * 189
            # Use a controlled next-candle path: 7 wins and 3 losses.
            for index in range(200, 210):
                candle_index = 60 + index
                candles[candle_index + 1]["close"] = candles[candle_index + 1]["open"] + (
                    1 if index < 7 else -1
                )
            result = backtest_asset(connector, asset, settings)

        self.assertEqual(result["operations"], 10)
        self.assertEqual(result["wins"], 7)
        self.assertEqual(result["losses"], 3)
        self.assertEqual(result["accuracy"], 70.0)
        self.assertTrue(result["approved"])

    def test_insufficient_history_is_not_approved(self):
        connector = FakeConnector(make_candles(240))
        result = backtest_asset(
            connector, {"symbol": "USDJPY-OTC", "active_id": 78}, {}
        )
        self.assertFalse(result["approved"])
        self.assertEqual(result["operations"], 0)

    def test_selection_returns_only_approved_assets_and_rechecks_all(self):
        assets = [
            {"symbol": "A-OTC", "active_id": 1},
            {"symbol": "B-OTC", "active_id": 2},
        ]
        results = [
            {"symbol": "A-OTC", "active_id": 1, "wins": 7, "losses": 3,
             "ties": 0, "operations": 10, "accuracy": 70.0, "approved": True,
             "reason": "Aprovado"},
            {"symbol": "B-OTC", "active_id": 2, "wins": 6, "losses": 4,
             "ties": 0, "operations": 10, "accuracy": 60.0, "approved": False,
             "reason": "Assertividade abaixo do mínimo"},
        ]
        with patch("asset_selector.backtest_asset", side_effect=results) as run:
            approved, report = select_qualified_assets(
                object(), assets, {}, stop_check=lambda: False
            )
        self.assertEqual(approved, [assets[0]])
        self.assertEqual(len(report), 2)
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
