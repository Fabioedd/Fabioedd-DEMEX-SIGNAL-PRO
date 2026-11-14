"""DEMO order runner with R$5 base, Soros 1, stop and take."""
from decimal import Decimal, ROUND_HALF_UP
import logging
import random
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
        self.paused = False  # compatibilidade; pendências não ativam pausa global
        self.pending_unknown_order = None
        self.pending_unknown_order_queue = []
        self._unknown_monitor_thread = None
        self._state_lock = threading.RLock()
        self._stopped = False
        self.stop_reason = None
        # Pausa global aleatória após liquidação.
        self.entry_cooldown_min_seconds = max(120, int(settings.get('entry_cooldown_min_seconds', 120)))
        self.entry_cooldown_max_seconds = max(self.entry_cooldown_min_seconds, min(180, int(settings.get('entry_cooldown_max_seconds', 180))))
        self.entry_cooldown_seconds = 0.0
        self.entry_cooldown_until = 0.0
        self.entry_callback = None
        self._cooldown_active = False
        self._last_cooldown_log_at = 0.0

    @property
    def has_pending_orders(self):
        with self._state_lock:
            return self.pending_unknown_order is not None or bool(self.pending_unknown_order_queue)

    @property
    def stopped(self):
        return self._stopped

    @stopped.setter
    def stopped(self, value):
        self._stopped = bool(value)

    def _entry_cooldown_remaining(self):
        """Retorna o tempo restante da trava global entre entradas."""
        now = time.monotonic()
        with self._state_lock:
            remaining = max(0.0, self.entry_cooldown_until - now)
            if remaining > 0:
                if (
                    not self._cooldown_active
                    or now - self._last_cooldown_log_at >= 15.0
                ):
                    log.warning(
                        "NOVA ENTRADA BLOQUEADA | intervalo global de %.0fs; "
                        "liberação em %.1fs.",
                        self.entry_cooldown_seconds,
                        remaining,
                    )
                    self._last_cooldown_log_at = now
                self._cooldown_active = True
            elif self._cooldown_active:
                log.info(
                    "INTERVALO CONCLUÍDO | %.0f segundos completos; "
                    "novas entradas liberadas.",
                    self.entry_cooldown_seconds,
                )
                self._cooldown_active = False
            return remaining

    def _register_confirmed_entry(self, pending, order_id):
        """Registra a entrada confirmada; não aplica espera fixa entre operações."""
        now = time.monotonic()
        confirmed_at = time.time()
        with self._state_lock:
            if pending.get("entry_confirmed"):
                return
            pending["entry_confirmed"] = True
            remaining = 0.0

        log.info(
            "ENTRADA CONFIRMADA | %s %s | ID %s | "
            "pausa global aleatória de 2 a 3 minutos após a liquidação.",
            pending["signal"]["symbol"],
            pending["signal"]["direction"],
            order_id,
        )
        callback = self.entry_callback
        if callback is not None:
            try:
                callback({
                    "order_id": order_id,
                    "symbol": pending["signal"]["symbol"],
                    "direction": pending["signal"]["direction"],
                    "entry": float(pending["amount"]),
                    "cooldown_seconds": 0,
                    "signal_timestamp": pending["signal"].get("detected_at_server_timestamp"),
                    "entry_timestamp": confirmed_at,
                    "reasons": pending["signal"].get("reasons", []),
                    "confidence": pending["signal"].get("confidence"),
                })
            except Exception:
                log.exception(
                    "Entrada confirmada, mas não foi possível enviar a notificação de entrada."
                )

    def _read_late_order_response(self):
        """Consulta exclusivamente o request_id original, nunca uma resposta alheia."""
        pending = self.pending_unknown_order or {}
        known_order_id = pending.get("order_id")
        if known_order_id is not None:
            return "accepted", known_order_id
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
                self.entry_cooldown_seconds = random.randint(self.entry_cooldown_min_seconds, self.entry_cooldown_max_seconds)
                self.entry_cooldown_until = time.monotonic() + self.entry_cooldown_seconds
                self._cooldown_active = False
                self._last_cooldown_log_at = 0.0
                log.info("PAUSA GLOBAL APÓS LIQUIDAÇÃO | %d segundos | DEMEX continua analisando os ativos.", self.entry_cooldown_seconds)

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
                "stop_reason": self.stop_reason if self.stopped else reason,
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
            log.warning("ROBÔ PARADO: %s", self.stop_reason or reason)
        return summary

    def _release_unknown_order_if_expired(self):
        # Uma ordem pendente bloqueia novas entradas até ser liquidada ou recusada.
        return False

    def _monitor_unknown_order(self):
        """Reconcilia a única ordem pendente; o scanner fica bloqueado até a liquidação."""
        while self.pending_unknown_order is not None or self.pending_unknown_order_queue:
            if self.pending_unknown_order is None and self.pending_unknown_order_queue:
                with self._state_lock:
                    self.pending_unknown_order = self.pending_unknown_order_queue.pop(0)
            # Aguarda a chamada original de execute_and_settle terminar seu finally
            # antes de reconciliar; evita corrida sobre a trava busy.
            with self._state_lock:
                original_execution_busy = self.busy
            if original_execution_busy:
                time.sleep(0.05)
                continue
            # A parada impede novas entradas, mas não interrompe a consulta
            # da ordem já enviada: é preciso conhecer seu resultado antes de fechar.
            self._release_unknown_order_if_expired()
            try:
                state, value = self._read_late_order_response()
                if state == "rejected":
                    pending = self.pending_unknown_order
                    self.connector.clear_pending_order_request(
                        pending.get("request_ref") if pending else None
                    )
                    with self._state_lock:
                        self.pending_unknown_order = None
                    log.warning(
                        "ORDEM NÃO EXECUTADA: a BullX devolveu recusa explícita após o timeout "
                        "(%s). DEMEX retomará a análise sem contabilizar entrada.", value
                    )
                    continue

                if state == "accepted":
                    order_id = value
                    accepted_pending = self.pending_unknown_order
                    if accepted_pending is not None:
                        self._register_confirmed_entry(accepted_pending, order_id)
                    log.info(
                        "PENDÊNCIA IDENTIFICADA | ID %s | consultando o resultado da mesma ordem, sem reenviar.",
                        order_id
                    )
                    while self.pending_unknown_order is not None:
                        try:
                            result, pnl = self.connector.wait_practice_result(
                                order_id, stop_check=None, timeout_seconds=30.0
                            )
                            # O resultado pode chegar enquanto o scanner já prepara
                            # outra ordem. Aguarda a execução atual terminar antes de
                            # atualizar net/Soros, sem liberar duas operações concorrentes.
                            while True:
                                with self._state_lock:
                                    pending = self.pending_unknown_order
                                    if pending is None:
                                        return
                                    if not self.busy:
                                        self.busy = True
                                        break
                                time.sleep(0.05)
                            try:
                                summary = self._apply_settlement(
                                    pending["signal"], pending["amount"], order_id, result, pnl
                                )
                            finally:
                                with self._state_lock:
                                    self.pending_unknown_order = None
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
                                "placar %d entradas, %d WIN, %d LOSS | sequência atual WIN %d/LOSS %d | "
                                "recorde WIN %d/LOSS %d | P&L R$ %+.2f",
                                order_id, result, summary["total_entries"],
                                summary["wins"], summary["losses"],
                                summary["current_win_streak"], summary["current_loss_streak"],
                                summary["max_win_streak"], summary["max_loss_streak"],
                                summary["session_net"]
                            )
                            break
                        except InterruptedError:
                            log.warning(
                                "Parada solicitada durante a espera do resultado da ordem %s. "
                                "Nenhuma nova entrada será enviada.", order_id
                            )
                            return
                        except TimeoutError:
                            log.warning(
                                "RESULTADO AINDA NÃO DISPONÍVEL | ID %s | nova consulta em 5 segundos; "
                                "a pendência continua bloqueando novas entradas até o resultado ser conhecido.", order_id
                            )
                            time.sleep(5)
                            continue
                        except Exception as exc:
                            if not is_transport_error(exc):
                                log.exception(
                                    "Não foi possível consultar o resultado da ordem %s. "
                                    "DEMEX continuará monitorando a mesma ordem e tentará novamente.", order_id
                                )
                                time.sleep(5)
                                continue
                            self.connector.connected = False
                            log.warning(
                                "Conexão caiu ao consultar a ordem reconciliada %s; "
                                "reconectando para consultar a mesma ordem.", order_id
                            )
                            self.connector.reconnect_forever(stop_check=None)

                time.sleep(2)
            except Exception:
                log.exception(
                    "Falha ao verificar a resposta tardia da ordem. "
                    "DEMEX permanece ativo e continuará monitorando a resposta tardia."
                )
                time.sleep(5)

        # Fecha a janela de corrida entre a última verificação da fila e a
        # saída da thread: uma nova ordem pode ter sido enfileirada nesse instante.
        with self._state_lock:
            if self._unknown_monitor_thread is threading.current_thread():
                self._unknown_monitor_thread = None
            restart_monitor = (
                self.pending_unknown_order is not None or bool(self.pending_unknown_order_queue)
            )
        if restart_monitor:
            self._start_unknown_order_monitor()

    def _start_unknown_order_monitor(self):
        with self._state_lock:
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
            cooldown_remaining = self._entry_cooldown_remaining()
            if cooldown_remaining > 0:
                log.warning(
                    "NOVA ENTRADA BLOQUEADA | pausa global após liquidação; "
                    "faltam %.0f segundos.",
                    cooldown_remaining,
                )
                return None
            if (
                self.busy
                or self.stopped
                or self.pending_unknown_order is not None
                or bool(self.pending_unknown_order_queue)
            ):
                log.warning(
                    "NOVA ENTRADA BLOQUEADA: já existe uma operação aguardando "
                    "confirmação ou resultado. O DEMEX só liberará outra entrada "
                    "depois da liquidação (ou recusa explícita) da ordem atual."
                )
                return None
            key = "{}|{}|{}".format(signal["symbol"], signal["direction"], signal.get("signal_timestamp"))
            if key == self.last_signal_key:
                log.warning("Sinal duplicado ignorado: %s", key)
                return None
            self.last_signal_key = key
            self.busy = True
        if self.stop_check and self.stop_check():
            with self._state_lock:
                self.busy = False
            raise InterruptedError("Parada solicitada antes do envio de uma nova ordem.")
        while True:
            try:
                practice_confirmed = (
                    self.connector.config.account_type == "PRACTICE"
                    and self.connector.client.get_balance_mode() == "PRACTICE"
                )
                break
            except PermissionError:
                with self._state_lock:
                    self.busy = False
                raise
            except Exception as exc:
                self.connector.connected = False
                log.warning(
                    "Resposta inesperada ao confirmar a conta PRACTICE (%s). "
                    "DEMEX vai reconectar e repetir a verificação, sem enviar ordem.",
                    exc
                )
                try:
                    self.connector.reconnect_forever(stop_check=self.stop_check)
                except (InterruptedError, PermissionError):
                    with self._state_lock:
                        self.busy = False
                    raise
                except Exception:
                    log.exception("Falha na reconexão durante a confirmação da conta; nova tentativa.")
                    time.sleep(5)
        if not practice_confirmed:
            with self._state_lock:
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
                new_pending = {
                    "signal": dict(signal),
                    "amount": amount,
                    "submitted_at": time.time(),
                    "reason": str(exc),
                    "request_ref": getattr(exc, "request_ref", None)
                        or getattr(self.connector, "pending_order_request", None),
                }
                with self._state_lock:
                    # Todas as ordens entram na mesma fila FIFO, sejam confirmadas
                    # ou de confirmação desconhecida. Isso preserva a ordem de envio.
                    self.pending_unknown_order_queue.append(new_pending)
                log.critical(
                    "CONFIRMAÇÃO DESCONHECIDA | %s %s | %s. "
                    "A solicitação original ficará em reconciliação; nenhuma nova "
                    "entrada será permitida até a confirmação do resultado.",
                    signal["symbol"], signal["direction"], exc
                )
                self._start_unknown_order_monitor()
                raise

            log.info(
                "ORDEM DEMO | %s | %s | R$ %.2f | ID %s",
                signal["symbol"], signal["direction"], amount, order_id
            )

            # A ordem foi confirmada. O monitor consulta o resultado em segundo plano,
            # mas o gerenciador e o scanner bloqueiam qualquer nova entrada até liquidar.
            pending = {
                "signal": dict(signal),
                "amount": amount,
                "submitted_at": time.time(),
                "order_id": order_id,
                "reason": "aguardando liquidação em segundo plano",
                "request_ref": None,
            }
            self._register_confirmed_entry(pending, order_id)
            with self._state_lock:
                self.pending_unknown_order_queue.append(pending)
            log.info(
                "ORDEM EM SEGUNDO PLANO | ID %s | %s %s | "
                "%d pendência(s) aguardando resultado; novas entradas bloqueadas.",
                order_id, signal["symbol"], signal["direction"],
                len(self.pending_unknown_order_queue) + (1 if self.pending_unknown_order else 0)
            )
            self._start_unknown_order_monitor()
            return None
        finally:
            with self._state_lock:
                self.busy = False
