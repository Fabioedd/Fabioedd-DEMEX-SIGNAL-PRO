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
        self.assertIn("Total investido: <b>R$ 5.00</b>", message)

    def test_opened_trade_message_shows_signal_and_entry_times_without_delay_field(self):
        notifier = TelegramNotifier("token", "chat")
        entry = {
            "symbol": "EURUSD-OTC",
            "direction": "CALL",
            "order_id": 123456,
            "entry": 5.0,
            "cooldown_seconds": 60,
            "signal_timestamp": 1_800_000_000,
            "entry_timestamp": 1_800_000_003,
            "confidence": 100,
        }
        with patch.object(notifier, "send", return_value=True) as send:
            result = notifier.send_trade_opened(entry)

        self.assertTrue(result)
        message = send.call_args.args[0]
        self.assertIn("Horário do sinal:", message)
        self.assertIn("Horário da entrada:", message)
        self.assertIn("Valor da entrada: <b>R$ 5.00</b>", message)
        self.assertIn("Conta: <b>PRACTICE/DEMO</b>", message)
        self.assertIn("Ordem: <b>123456</b>", message)
        self.assertIn("60 segundos", message)
        self.assertNotIn("Tempo entre sinal e entrada", message)

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

    def test_final_report_contains_full_session_financial_summary(self):
        notifier = TelegramNotifier("token", "chat")
        with patch.object(notifier, "send", return_value=True) as send:
            notifier.send_session_start(
                account="PRACTICE/DEMO", market="OTC", timeframe="M1",
                expiry_minutes=1, assets_count=70, initial_entry=5,
                stop_loss=50, take_profit=30
            )
            notifier.send_trade_result({
                "symbol": "AUDCHF-OTC", "direction": "PUT", "entry": 5,
                "result": "WIN", "pnl": 4.2, "session_net": 4.2,
                "next_entry": 9.2, "total_entries": 1, "wins": 1,
                "losses": 0, "ties": 0, "win_rate": 100, "stopped": False,
            })
            notifier.send_trade_result({
                "symbol": "EURUSD-OTC", "direction": "CALL", "entry": 9.2,
                "result": "LOSS", "pnl": -9.2, "session_net": -5,
                "next_entry": 5, "total_entries": 2, "wins": 1,
                "losses": 1, "ties": 0, "win_rate": 50, "stopped": True,
                "stop_reason": "STOP LOSS atingido",
                "current_win_streak": 0, "current_loss_streak": 1,
                "max_win_streak": 1, "max_loss_streak": 1,
            })
            notifier.send_session_end(
                reason="STOP LOSS atingido", total_entries=2,
                wins=1, losses=1, ties=0, session_net=-5
            )

        message = send.call_args.args[0]
        self.assertIn("STOP LOSS atingido", message)
        self.assertIn("Total de entradas: <b>2</b>", message)
        self.assertIn("WIN: <b>1</b> | LOSS: <b>1</b> | TIE: <b>0</b>", message)
        self.assertIn("Assertividade: <b>50.00%</b>", message)
        self.assertIn("Sequência atual: WIN <b>0</b> | LOSS <b>1</b>", message)
        self.assertIn("Recorde na sessão: WIN <b>1</b> seguidos | LOSS <b>1</b> seguidos", message)
        self.assertIn("Entrada inicial: <b>R$ 5.00</b>", message)
        self.assertIn("Total investido nas entradas: <b>R$ 14.20</b>", message)
        self.assertIn("Última entrada realizada: <b>R$ 9.20</b>", message)
        self.assertIn("Próxima entrada prevista: <b>R$ 5.00</b>", message)
        self.assertIn("Limite Stop Loss: <b>R$ 50.00</b>", message)
        self.assertIn("Meta Take Profit: <b>R$ 30.00</b>", message)
        self.assertIn("-5.00 BRL", message)


if __name__ == "__main__":
    unittest.main()
