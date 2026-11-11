import unittest
from unittest.mock import patch

from telegram_notifier import TelegramNotifier


class TelegramNotifierTests(unittest.TestCase):
    def test_disabled_without_credentials(self):
        notifier = TelegramNotifier()
        self.assertFalse(notifier.enabled)
        self.assertFalse(notifier.send("hello"))

    def test_trade_message_contains_asset_result_and_updated_score(self):
        notifier = TelegramNotifier("token", "chat")
        with patch.object(notifier, "send", return_value=True) as send:
            result = notifier.send_trade_result({
                "symbol": "SUIUSD-OTC", "direction": "PUT", "entry": 5.0,
                "result": "WIN", "pnl": 4.2, "session_net": 4.2,
                "next_entry": 9.2, "total_entries": 1, "wins": 1,
                "losses": 0, "ties": 0, "win_rate": 100.0, "stopped": False,
            })
        self.assertTrue(result)
        message = send.call_args.args[0]
        self.assertIn("SUIUSD-OTC", message)
        self.assertIn("WIN", message)
        self.assertIn("LOSS: <b>0</b>", message)
        self.assertIn("+4.20 BRL", message)

    def test_html_escapes_asset_name(self):
        notifier = TelegramNotifier("token", "chat")
        with patch.object(notifier, "send", return_value=True) as send:
            notifier.send_trade_result({
                "symbol": "A&B", "direction": "CALL", "entry": 5,
                "result": "LOSS", "pnl": -5, "session_net": -5,
                "next_entry": 5, "total_entries": 1, "wins": 0,
                "losses": 1, "ties": 0, "win_rate": 0, "stopped": False,
            })
        self.assertIn("A&amp;B", send.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
