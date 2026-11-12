"""Outbound-only Telegram signal notifications for DEMEX."""
import html
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends confirmed CALL/PUT signals; never polls or accepts Telegram commands."""

    API_BASE = "https://api.telegram.org"

    def __init__(self, bot_token="", chat_id="", timeout=8):
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.timeout = timeout

    @classmethod
    def from_env(cls):
        return cls(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))

    @property
    def enabled(self):
        return bool(self.bot_token and self.chat_id)

    def send_signal(self, candidate):
        """Send one signal already selected and confirmed by the strategy."""
        if not self.enabled:
            return False
        symbol = html.escape(str(candidate.get("symbol", "—")))
        direction = str(candidate.get("direction", "—")).upper()
        direction_label = {"CALL": "COMPRA / CALL", "PUT": "VENDA / PUT"}.get(
            direction, direction
        )
        rsi = candidate.get("rsi")
        try:
            rsi_text = "{:.2f}".format(float(rsi)) if rsi is not None else "—"
        except (TypeError, ValueError):
            rsi_text = "—"
        text = (
            "📡 <b>DEMEX — SINAL CONFIRMADO</b>\n"
            "Ativo: <b>{}</b>\n"
            "Direção: <b>{}</b>\n"
            "Período: <b>M1</b> | Expiração: <b>1 minuto</b>\n"
            "RSI: <b>{}</b>"
        ).format(symbol, html.escape(direction_label), rsi_text)
        return self.send(text)

    def send(self, message):
        """Best-effort delivery: Telegram failures never interrupt trading."""
        if not self.enabled:
            return False
        url = "{}/bot{}/sendMessage".format(self.API_BASE, self.bot_token)
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not result.get("ok"):
                log.warning("Telegram recusou a notificação do sinal.")
                return False
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
            # A falha do Telegram nunca deve interromper nem repetir uma ordem.
            log.warning("Não foi possível enviar o sinal ao Telegram.")
            return False
