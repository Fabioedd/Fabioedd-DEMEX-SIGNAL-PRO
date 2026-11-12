import unittest
from unittest.mock import patch

from telegram_notifier import TelegramNotifier


class TelegramNotifierTests(unittest.TestCase):
    def test_disabled_without_credentials(self):
        notifier = TelegramNotifier()
        self.assertFalse(notifier.enabled)
        self.assertFalse(notifier.send_signal({"symbol": "EURUSD-OTC", "direction": "CALL"}))

    def test_sends_confirmed_call_signal(self):
        notifier = TelegramNotifier("token", "chat")
        candidate = {
            "symbol": "EURUSD-OTC",
            "direction": "CALL",
            "rsi": 28.45,
        }
        with patch.object(notifier, "send", return_value=True) as send:
            self.assertTrue(notifier.send_signal(candidate))
        message = send.call_args.args[0]
        self.assertIn("EURUSD-OTC", message)
        self.assertIn("COMPRA / CALL", message)
        self.assertIn("M1", message)
        self.assertIn("28.45", message)

    def test_sends_put_signal_and_escapes_asset_name(self):
        notifier = TelegramNotifier("token", "chat")
        with patch.object(notifier, "send", return_value=True) as send:
            notifier.send_signal({"symbol": "A&B", "direction": "PUT", "rsi": 72})
        message = send.call_args.args[0]
        self.assertIn("A&amp;B", message)
        self.assertIn("VENDA / PUT", message)

    def test_signal_delivery_failure_is_non_fatal(self):
        notifier = TelegramNotifier("token", "chat")
        with patch.object(notifier, "send", return_value=False):
            self.assertFalse(notifier.send_signal({
                "symbol": "EURUSD-OTC", "direction": "CALL"
            }))


if __name__ == "__main__":
    unittest.main()
