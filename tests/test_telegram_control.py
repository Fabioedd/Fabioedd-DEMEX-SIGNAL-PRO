import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

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



    def test_start_robot_writes_pid_for_telegram_and_termux_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = Mock()
            process.pid = 4321
            process.poll.return_value = None
            control = TelegramControl("token", "9246590305")
            with patch("telegram_control.STOP_FILE", root / ".demex_stop"), \
                 patch("telegram_control.PID_FILE", root / ".demex-telegram-robot.pid"), \
                 patch("telegram_control.SHELL_PID_FILE", root / ".demex.pid"), \
                 patch("telegram_control.ROBOT_LOG", root / "robot.log"), \
                 patch("telegram_control.find_robot_pid", side_effect=[None, 4321]), \
                 patch("telegram_control.subprocess.Popen", return_value=process), \
                 patch.object(control, "reply") as reply:
                control.start_robot(9246590305)
            self.assertEqual((root / ".demex-telegram-robot.pid").read_text(), "4321")
            self.assertEqual((root / ".demex.pid").read_text(), "4321")
            reply.assert_called_once()

    def test_stop_completion_clears_both_robot_pid_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            telegram_pid = root / ".demex-telegram-robot.pid"
            shell_pid = root / ".demex.pid"
            stop_file = root / ".demex_stop"
            telegram_pid.write_text("4321")
            shell_pid.write_text("4321")
            stop_file.touch()
            control = TelegramControl("token", "9246590305")
            control.stop_requested_pid = 4321
            with patch("telegram_control.PID_FILE", telegram_pid), \
                 patch("telegram_control.SHELL_PID_FILE", shell_pid), \
                 patch("telegram_control.STOP_FILE", stop_file), \
                 patch("telegram_control._pid_is_demex", return_value=False), \
                 patch.object(control, "reply") as reply:
                control.check_stopped_process()
            self.assertFalse(telegram_pid.exists())
            self.assertFalse(shell_pid.exists())
            self.assertFalse(stop_file.exists())
            self.assertIsNone(control.stop_requested_pid)
            reply.assert_called_once()

if __name__ == "__main__":
    unittest.main()
