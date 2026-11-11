import unittest
from unittest.mock import patch

from telegram_control import (
    TelegramControl,
    is_authorized_chat,
    parse_command,
)


class TelegramCommandTests(unittest.TestCase):
    def test_parse_commands_and_bot_suffix(self):
        self.assertEqual(parse_command("/start"), "/start")
        self.assertEqual(parse_command("/STOP@FabioBot"), "/stop")
        self.assertEqual(parse_command("/status detalhes"), "/status")
        self.assertIsNone(parse_command("olá"))
        self.assertIsNone(parse_command(""))

    def test_only_configured_private_chat_is_authorized(self):
        allowed = {"chat": {"id": 9246590305, "type": "private"}}
        group = {"chat": {"id": 9246590305, "type": "group"}}
        other = {"chat": {"id": 123, "type": "private"}}
        self.assertTrue(is_authorized_chat(allowed, "9246590305"))
        self.assertFalse(is_authorized_chat(group, "9246590305"))
        self.assertFalse(is_authorized_chat(other, "9246590305"))

    def test_unauthorized_update_is_ignored(self):
        control = TelegramControl("token", "9246590305")
        with patch.object(control, "start_robot") as start, patch.object(control, "reply") as reply:
            control.handle_update({
                "update_id": 1,
                "message": {
                    "text": "/start",
                    "chat": {"id": 123, "type": "private"},
                },
            })
        start.assert_not_called()
        reply.assert_not_called()

    def test_help_command_replies_with_controls(self):
        control = TelegramControl("token", "9246590305")
        with patch.object(control, "reply") as reply:
            control.handle_update({
                "update_id": 2,
                "message": {
                    "text": "/help",
                    "chat": {"id": 9246590305, "type": "private"},
                },
            })
        self.assertIn("/start", reply.call_args.args[1])
        self.assertIn("/stop", reply.call_args.args[1])
        self.assertIn("/status", reply.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
