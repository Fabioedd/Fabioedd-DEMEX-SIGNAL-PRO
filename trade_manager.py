"""DEMO order runner with R$5 base, Soros 1, stop and take."""
from decimal import Decimal, ROUND_HALF_UP
import logging
import threading
import time

from bullex_connector import is_transport_error, OrderConfirmationUnknownError

log = logging.getLogger(__name__)


def money(v):
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class DemoTrader:
    def __init__(self, connector, settings, stop_check=None):
        self.connector = connector
        self.stop_check = stop_check
        self.expiry = int(settings.get("expiry_minutes", 1))
        cfg = settings["trading"]
        self.base = money(cfg["initial_entry_brl"])
        self.stop = money(cfg["stop_loss_brl"])
        self.take = money(cfg["take_profit_brl"])
        self.net = Decimal("0.00")
        self.total_entries = 0
        self.wins = 0
        self.losses = 0
        self.ties = 0
        self.current_win_streak = 0
        self.current_loss_streak = 0
        self.max_win_streak = 0
        self.max_loss_streak = 0
        self.late_settlement_callback = None
        self.next_entry = self.base
        self.soros_step = 0
        self.last_signal_key = None
        self.busy = False
        self.paused = False
        self.pending_unknown_order = None
        self._unknown_monitor_thread = None
        self._state_lock = threading.RLock()
        self._stopped = False
        self.stop_reason = None

    @property
    def stopped(self):
        return self._stopped

    @stopped.setter
    def stopped(self, value):
        # main.py still requests a stop when it catches an unknown confirmation.
        # Convert that legacy stop request into a recoverable pause. An explicit
        # user stop (/stop) remains authoritative because stop_check is then true.
        if value and self.paused and not (self.stop_check and self.stop_check()):
            log.warning(
                "ENCERRAMENTO AUTOMÁTICO ADIADO: existe uma ordem com confirmação "
                "desconhecida. DEMEX permanece ativo em reconciliação, sem novas entradas."
            )
            return
        self._stopped = bool(value)

    def _read_late_order_response(self):
        """Consulta exclusivamente o request_id original, nunca uma resposta alheia."""
        pending = self.pending_unknown_order or {}
        request_ref = pending.get("request_ref")
        reader = getattr(self.connector, "read_order_confirmation", None)
        if request_ref is None or reader is None:
            return "pending", None
        return reader(request_ref)

    def _apply_settlement(self, signal, amount, order_id, result, pnl_raw):
        """Atualiza placar e gerenciamento financeiro para uma ordem já identificada."""
        pnl = money(pnl_raw)
        with self._state_lock:
            self.net = money(self.net + pnl)
            self.total_entries += 1
            if result == "WIN":
                self.wins += 1
                self.current_win_streak += 1
                self.current_loss_streak = 0
            elif result == "LOSS":
                self.losses += 1
                self.current_loss_streak += 1
                self.current_win_streak = 0
            else:
                self.ties += 1
                self.current_win_streak = 0
                self.current_loss_streak = 0
            self.max_win_streak = max(self.max_win_streak, self.current_win_streak)
            self.max_loss_streak = max(self.max_loss_streak, self.current_loss_streak)

            decisive = self.wins + self.losses
            win_rate = (100.0 * self.wins / decisive) if decisive else 0.0

            # Soros nível 1: apenas uma recuperação após WIN; depois reinicia.
            if result == "WIN" and self.soros_step == 0:
                self.next_entry = money(self.base + pnl)
                self.soros_step = 1
            else:
                self.next_entry = self.base
                self.soros_step = 0

            if self.net <= -self.stop:
                self.stopped = True
                reason = "STOP LOSS atingido"
                self.stop_reason = reason
            elif self.net >= self.take:
                self.stopped = True
                reason = "TAKE PROFIT atingido"
                self.stop_reason = reason
            else:
                reason = None

            if not self.stopped:
                self.next_entry = min(self.next_entry, money(self.stop + self.net))

            summary = {
                "order_id": order_id,
                "symbol": signal["symbol"],
                "direction": signal["direction"],
                "entry": float(amount),
                "expiry_minutes": self.expiry,
                "result": result,
                "pnl": float(pnl),
                "session_net": float(self.net),
                "next_entry": float(self.next_entry),
                "stopped": self.stopped,
                "stop_reason": reason,
                "total_entries": self.total_entries,
                "wins": self.wins,
                "losses": self.losses,
                "ties": self.ties,
                "win_rate": round(win_rate, 2),
                "current_win_streak": self.current_win_streak,
                "current_loss_streak": self.current_loss_streak,
                "max_win_streak": self.max_win_streak,
                "max_loss_streak": self.max_loss_streak,
            }

        log.info(
            "RESULTADO %s | P&L R$ %.2f | acumulado R$ %.2f | próxima entrada R$ %.2f",
            result, pnl, self.net, self.next_entry
        )
        if self.stopped:
            log.warning("ROBÔ PARADO: %s", reason)
        return summary

    def _monitor_unknown_order(self):
        """Acompanha a resposta tardia sem reenviar; só libera novas entradas após resolver."""
        while self.paused and not self.stopped:
            if self.stop_check and self.stop_check():
                log.warning(
                    "Parada solicitada pelo usuário durante reconciliação; "
                    "nenhuma nova ordem será enviada."
                )
                return
            try:
                state, value = self._read_late_order_response()
                if state == "rejected":
                    pending = self.pending_unknown_order
                    self.connector.clear_pending_order_request(
                        pending.get("request_ref") if pending else None
                    )
                    with self._state_lock:
                        self.paused = False
                        self.pending_unknown_order = None
                    log.warning(
                        "ORDEM NÃO EXECUTADA: a BullX devolveu recusa explícita após o timeout "
                        "(%s). DEMEX retomará a análise sem contabilizar entrada.", value
                    )
                    return

                if state == "accepted":
                    order_id = value
                    log.warning(
                        "ORDEM RECONCILIADA: a BullX devolveu tardiamente o ID %s. "
                        "O DEMEX consultará o resultado desta mesma ordem, sem reenviar.",
                        order_id
                    )
                    while self.paused and not self.stopped:
                        try:
                            result, pnl = self.connector.wait_practice_result(order_id)
                            with self._state_lock:
                                pending = self.pending_unknown_order
                                if pending is None:
                                    return
                                # Reserva o gerenciador durante a contabilização.
                                # Assim, o loop principal não pode abrir outra ordem
                                # entre a confirmação tardia e a atualização do saldo.
                                self.paused = False
                                self.pending_unknown_order = None
                                self.busy = True
                            try:
                                summary = self._apply_settlement(
                                    pending["signal"], pending["amount"], order_id, result, pnl
                                )
                            finally:
                                with self._state_lock:
                                    self.busy = False
                            self.connector.clear_pending_order_request(pending.get("request_ref"))
                            callback = self.late_settlement_callback
                            if callback is not None:
                                try:
                                    callback(summary)
                                except Exception:
                                    log.exception(
                                        "Resultado tardio contabilizado, mas a notificação não foi enviada."
                                    )
                            log.info(
                                "ORDEM DESCONHECIDA RESOLVIDA | ID %s | %s | "
                                "placar %d entradas, %d WIN, %d LOSS | P&L R$ %+.2f",
                                order_id, result, summary["total_entries"],
                                summary["wins"], summary["losses"], summary["session_net"]
                            )
                            return
                        except Exception as exc:
                            if not is_transport_error(exc):
                                log.exception(
                                    "Não foi possível consultar o resultado da ordem %s. "
                                    "DEMEX continuará pausado e tentará novamente.", order_id
                                )
                                time.sleep(5)
                                continue
                            self.connector.connected = False
                            log.warning(
                                "Conexão caiu ao consultar a ordem reconciliada %s; "
                                "reconectando para consultar a mesma ordem.", order_id
                            )
                            self.connector.reconnect_forever(stop_check=self.stop_check)

                time.sleep(2)
            except Exception:
                log.exception(
                    "Falha ao verificar a resposta tardia da ordem. "
                    "DEMEX permanece ativo, pausado para novas entradas, e tentará novamente."
                )
                time.sleep(5)

    def _start_unknown_order_monitor(self):
        thread = self._unknown_monitor_thread
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(
            target=self._monitor_unknown_order,
            name="demex-unknown-order-monitor",
            daemon=True,
        )
        self._unknown_monitor_thread = thread
        thread.start()

    def execute_and_settle(self, signal, pre_order_check=None):
        with self._state_lock:
            if self.busy or self.stopped or self.paused:
                return None
            key = "{}|{}|{}".format(signal["symbol"], signal["direction"], signal.get("signal_timestamp"))
            if key == self.last_signal_key:
                log.warning("Sinal duplicado ignorado: %s", key)
                return None
            self.last_signal_key = key
            self.busy = True
        if self.connector.config.account_type != "PRACTICE" or self.connector.client.get_balance_mode() != "PRACTICE":
            self.busy = False
            raise PermissionError("Robô bloqueado: conta PRACTICE/DEMO não confirmada.")
        try:
            amount = min(self.next_entry, money(self.stop + self.net))
            if amount <= 0:
                self.stopped = True
                return None
            if pre_order_check is not None and not pre_order_check():
                log.info("Ordem cancelada: validação final do sinal não autorizou a entrada.")
                return None

            try:
                order_id = self.connector.place_practice_order(
                    signal["symbol"], signal["direction"], float(amount), self.expiry
                )
            except OrderConfirmationUnknownError as exc:
                with self._state_lock:
                    self.paused = True
                    self.pending_unknown_order = {
                        "signal": dict(signal),
                        "amount": amount,
                        "submitted_at": time.time(),
                        "reason": str(exc),
                        "request_ref": getattr(exc, "request_ref", None)
                            or getattr(self.connector, "pending_order_request", None),
                    }
                log.critical(
                    "CONFIRMAÇÃO DESCONHECIDA | %s %s | %s. "
                    "A sessão não será encerrada: DEMEX continuará ativo, "
                    "monitorando a resposta da mesma solicitação. Novas entradas "
                    "ficam bloqueadas até a ordem ser identificada ou recusada.",
                    signal["symbol"], signal["direction"], exc
                )
                self._start_unknown_order_monitor()
                raise

            log.info(
                "ORDEM DEMO | %s | %s | R$ %.2f | ID %s",
                signal["symbol"], signal["direction"], amount, order_id
            )

            # A ordem já foi enviada: em caso de queda, reconectar e consultar
            # o MESMO order_id. Nunca enviar uma segunda ordem para substituir esta.
            while True:
                try:
                    result, pnl_raw = self.connector.wait_practice_result(order_id)
                    break
                except Exception as exc:
                    if not is_transport_error(exc):
                        raise
                    self.connector.connected = False
                    log.warning(
                        "Conexão caiu aguardando resultado da ordem %s (%s); "
                        "reconectando para consultar a mesma ordem, sem duplicá-la.",
                        order_id, exc
                    )
                    self.connector.reconnect_forever(stop_check=self.stop_check)

            return self._apply_settlement(signal, amount, order_id, result, pnl_raw)
        finally:
            self.busy = False
