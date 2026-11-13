"""Optional Telegram notifications for DEMEX; uses only the Python standard library."""
import html
import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime

log = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends session and settled-trade reports without affecting trading."""

    API_BASE = "https://api.telegram.org"

    def __init__(self, bot_token="", chat_id="", timeout=8):
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.timeout = timeout
        # Session totals are tracked here so the final report can be complete
        # without coupling the trading manager to Telegram.
        self.initial_entry = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.total_invested = 0.0
        self.last_entry = 0.0
        self.next_entry = 0.0
        self.current_win_streak = 0
        self.current_loss_streak = 0
        self.max_win_streak = 0
        self.max_loss_streak = 0

    @classmethod
    def from_env(cls):
        return cls(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))

    @property
    def enabled(self):
        return bool(self.bot_token and self.chat_id)

    def send(self, message):
        if not self.enabled:
            return False
        if not shutil.which("curl"):
            log.warning("Comando curl indisponível; notificação Telegram não enviada.")
            return False
        url = "{}/bot{}/sendMessage".format(self.API_BASE, self.bot_token)
        body = json.dumps({
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, ensure_ascii=False)
        # URL/token ficam no stdin do curl, nunca nos argumentos do processo.
        config = "\n".join((
            "url = {}".format(json.dumps(url)),
            'request = "POST"',
            'header = "Content-Type: application/json"',
            "data = {}".format(json.dumps(body)),
            "silent",
            "show-error",
            "max-time = {}".format(self.timeout),
            "",
        ))
        # Pequenas tentativas adicionais recuperam quedas breves de rede sem
        # alterar o fluxo de ordens nem registrar credenciais.
        for attempt in range(3):
            try:
                response = subprocess.run(
                    ["curl", "-4", "--http1.1", "--config", "-"],
                    input=config,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout + 2,
                    check=False,
                )
                if response.returncode != 0:
                    raise RuntimeError("Falha de comunicação com o Telegram.")
                result = json.loads(response.stdout)
                if not result.get("ok"):
                    log.warning("Telegram recusou uma notificação do DEMEX.")
                    return False
                return True
            except (subprocess.SubprocessError, OSError, ValueError, RuntimeError):
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        log.warning("Não foi possível enviar notificação ao Telegram após 3 tentativas.")
        return False

    def send_session_start(self, account, market, timeframe, expiry_minutes,
                            assets_count, initial_entry, stop_loss, take_profit,
                            entry_cooldown_seconds=60):
        self.initial_entry = float(initial_entry)
        self.stop_loss = float(stop_loss)
        self.take_profit = float(take_profit)
        self.total_invested = 0.0
        self.last_entry = 0.0
        self.next_entry = self.initial_entry
        text = (
            "🟦 <b>DEMEX INICIADO</b>\n"
            "Conta: <b>{}</b>\nMercado: <b>{}</b>\n"
            "Período: <b>{}</b> | Expiração: <b>{} min</b>\n"
            "Estratégia: <b>GO 2024 FILTRADO</b>\n"
            "Indicadores: <b>SMA 1/34 + WMA 5 | EMA 21/45 | ADX 14 >= 35</b>\n"
            "Intervalo entre entradas: <b>{} segundos</b>\n"
            "Ativos monitorados: <b>{}</b>\nEntrada inicial: <b>R$ {:.2f}</b>\n"
            "Stop Loss: <b>R$ {:.2f}</b> | Take Profit: <b>R$ {:.2f}</b>"
        ).format(html.escape(str(account)), html.escape(str(market)),
                 html.escape(str(timeframe)), int(expiry_minutes),
                 int(entry_cooldown_seconds), int(assets_count),
                 self.initial_entry, self.stop_loss, self.take_profit)
        return self.send(text)

    def send_trade_opened(self, entry):
        symbol = html.escape(str(entry.get("symbol", "—")))
        direction = html.escape(str(entry.get("direction", "—")))
        order_id = html.escape(str(entry.get("order_id", "—")))
        amount = float(entry.get("entry", 0))
        cooldown = int(entry.get("cooldown_seconds", 60))
        def local_time(value):
            try:
                return datetime.fromtimestamp(float(value)).astimezone().strftime("%H:%M:%S")
            except (TypeError, ValueError, OSError, OverflowError):
                return "—"

        confluences = "SMA 1/34 + WMA 5 | EMA 21/45 | ADX 14"
        confidence = entry.get("confidence")
        confidence_line = (
            "Confiança do sinal: <b>{:.0f}%</b>\n".format(float(confidence))
            if isinstance(confidence, (int, float)) else ""
        )
        signal_time = local_time(entry.get("signal_timestamp"))
        entry_time = local_time(entry.get("entry_timestamp"))
        return self.send(
            "🎯 <b>DEMEX SIGNAL PRO</b>\n"
            "🟢 <b>SINAL CONFIRMADO</b>\n"
            "Ativo: <b>{}</b>\nDireção: <b>{}</b>\n"
            "Indicador: <b>GO 2024 FILTRADO</b>\n"
            "Confluências: <b>{}</b>\n"
            "{}"
            "⏱️ <b>HORÁRIOS</b>\n"
            "Horário do sinal: <b>{}</b>\n"
            "Horário da entrada: <b>{}</b>\n\n"
            "💰 <b>INFORMAÇÕES DA OPERAÇÃO</b>\n"
            "Valor da entrada: <b>R$ {:.2f}</b>\n"
            "Conta: <b>PRACTICE/DEMO</b>\nOrdem: <b>{}</b>\n"
            "Próxima entrada liberada em: <b>{} segundos</b>."
            .format(symbol, direction, confluences, confidence_line,
                    signal_time, entry_time, amount, order_id, cooldown)
        )

    def send_trade_result(self, summary):
        result = str(summary.get("result", "RESULTADO")).upper()
        emoji = {"WIN": "🟢", "LOSS": "🔴", "TIE": "🟡"}.get(result, "⚪")
        symbol = html.escape(str(summary.get("symbol", "—")))
        direction = html.escape(str(summary.get("direction", "—")))
        total = int(summary.get("total_entries", 0))
        wins = int(summary.get("wins", 0))
        losses = int(summary.get("losses", 0))
        ties = int(summary.get("ties", 0))
        pnl = float(summary.get("pnl", 0))
        net = float(summary.get("session_net", 0))
        entry = float(summary.get("entry", 0))
        win_rate = float(summary.get("win_rate", 0))
        next_entry = float(summary.get("next_entry", 0))

        # Accumulate the actual stakes reported by each settled operation.
        self.total_invested += entry
        self.last_entry = entry
        self.next_entry = next_entry
        self.current_win_streak = int(summary.get("current_win_streak", self.current_win_streak))
        self.current_loss_streak = int(summary.get("current_loss_streak", self.current_loss_streak))
        self.max_win_streak = max(self.max_win_streak, int(summary.get("max_win_streak", 0)))
        self.max_loss_streak = max(self.max_loss_streak, int(summary.get("max_loss_streak", 0)))

        text = (
            "📊 <b>DEMEX — RESULTADO DA OPERAÇÃO</b>\n\n"
            "Ativo: <b>{}</b>\nDireção: <b>{}</b>\n"
            "Entrada: <b>R$ {:.2f}</b>\n"
            "Resultado: {} <b>{}</b> | <b>{:+.2f} BRL</b>\n\n"
            "📈 <b>PLACAR ATUALIZADO</b>\n"
            "WIN: <b>{}</b> | LOSS: <b>{}</b> | TIE: <b>{}</b>\n"
            "Operações: <b>{}</b> | Aproveitamento: <b>{:.2f}%</b>\n"
            "Total investido: <b>R$ {:.2f}</b>\n"
            "Sequência atual: WIN <b>{}</b> | LOSS <b>{}</b>\n"
            "Recorde na sessão: WIN <b>{}</b> seguidos | LOSS <b>{}</b> seguidos\n"
            "Resultado desta sessão: <b>{:+.2f} BRL</b>\n"
            "Próxima entrada: <b>R$ {:.2f}</b>"
        ).format(symbol, direction, entry, emoji, result, pnl, wins, losses, ties,
                 total, win_rate, self.total_invested,
                 self.current_win_streak, self.current_loss_streak,
                 self.max_win_streak, self.max_loss_streak, net, next_entry)
        if summary.get("stopped"):
            reason = html.escape(str(summary.get("stop_reason") or "Limite da sessão atingido"))
            text += "\n\n⛔ <b>SESSÃO ENCERRADA:</b> " + reason
        return self.send(text)

    def send_session_end(self, reason, total_entries, wins, losses, ties, session_net):
        decisive = int(wins) + int(losses)
        win_rate = (100.0 * int(wins) / decisive) if decisive else 0.0
        text = (
            "⛔ <b>DEMEX — RELATÓRIO FINAL DA SESSÃO</b>\n\n"
            "Motivo do encerramento: <b>{}</b>\n"
            "Horário: <b>{}</b>\n\n"
            "📊 <b>QUANTIDADE DE OPERAÇÕES</b>\n"
            "Total de entradas: <b>{}</b>\n"
            "WIN: <b>{}</b> | LOSS: <b>{}</b> | TIE: <b>{}</b>\n"
            "Assertividade: <b>{:.2f}%</b>\n"
            "Sequência atual: WIN <b>{}</b> | LOSS <b>{}</b>\n"
            "Recorde na sessão: WIN <b>{}</b> seguidos | LOSS <b>{}</b> seguidos\n\n"
            "💰 <b>RESUMO FINANCEIRO</b>\n"
            "Entrada inicial: <b>R$ {:.2f}</b>\n"
            "Total investido nas entradas: <b>R$ {:.2f}</b>\n"
            "Última entrada realizada: <b>R$ {:.2f}</b>\n"
            "Próxima entrada prevista: <b>R$ {:.2f}</b>\n"
            "Limite Stop Loss: <b>R$ {:.2f}</b>\n"
            "Meta Take Profit: <b>R$ {:.2f}</b>\n"
            "RESULTADO LÍQUIDO: <b>{:+.2f} BRL</b>"
        ).format(
            html.escape(str(reason)),
            datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            int(total_entries), int(wins), int(losses), int(ties), win_rate,
            self.current_win_streak, self.current_loss_streak,
            self.max_win_streak, self.max_loss_streak,
            self.initial_entry, self.total_invested, self.last_entry,
            self.next_entry, self.stop_loss, self.take_profit, float(session_net)
        )
        return self.send(text)
