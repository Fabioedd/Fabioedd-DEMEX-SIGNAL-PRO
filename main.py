"""DEMEX automatic signal trader — PRACTICE/DEMO only."""
import json
import logging
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from bullex_connector import (
    BullexConfig, BullexReadOnlyConnector, is_transport_error,
    OrderRejectedError, OrderConfirmationUnknownError,
)
from strategies.my_strategy import get_intrabar_signal, get_signal_at_index
from trade_manager import DemoTrader
from telegram_notifier import TelegramNotifier
from robot_lock import acquire_robot_lock
from entry_timing import (
    filter_market_assets,
    is_candle_still_open,
    is_next_candle_entry_window,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

STOP_FILE = Path(".demex_stop")
ASSET_REFRESH_INTERVAL_SECONDS = 900
ENTRY_CONFIRMATION_TOLERANCE_SECONDS = 3.0
MAX_PENDING_SIGNALS = 1
_scan_pass_number = 0


def scan_delay(settings):
    """Mantém a varredura no intervalo configurado (padrão aprovado: 2 segundos)."""
    return max(1, min(3, int(settings.get("scan_interval_seconds", 2))))


def load_settings():
    with open("settings.json", encoding="utf-8") as f:
        return json.load(f)


def alert(message, enabled=True):
    print("\\a" + message, flush=True)
    if enabled:
        try:
            subprocess.Popen(["termux-tts-speak", message])
        except (FileNotFoundError, OSError):
            pass


def normalize_timestamp(value):
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    return ts / 1000.0 if ts > 10_000_000_000 else ts


def get_market_assets(connector, settings, stop_check=None):
    """Retorna somente ativos OTC binários que a corretora informa disponíveis."""
    mode = str(settings.get("market_mode", "OTC")).upper()
    if mode != "OTC":
        raise RuntimeError("Este robô está configurado para analisar exclusivamente ativos OTC.")
    while True:
        try:
            availability = connector.get_otc_asset_availability()
            break
        except Exception as exc:
            if not is_transport_error(exc):
                raise
            connector.connected = False
            logging.warning("Conexão perdida ao atualizar ativos OTC: %s", exc)
            connector.reconnect_forever(stop_check=stop_check)
    available = [
        {"symbol": item["symbol"], "active_id": item["active_id"]}
        for item in availability if item.get("available") is True
    ]
    unavailable_count = len(availability) - len(available)
    logging.info(
        "DISPONIBILIDADE OTC: %d disponíveis; %d fechados ou suspensos. "
        "Atualização a cada %d minutos.",
        len(available), unavailable_count, ASSET_REFRESH_INTERVAL_SECONDS // 60
    )
    return filter_market_assets(available, "OTC")


def scan_once(connector, settings, assets, max_candidates=1, excluded_keys=None):
    """Retorna o primeiro sinal intrabar; a entrada ocorre na próxima vela."""
    global _scan_pass_number
    _scan_pass_number += 1
    if settings.get("timeframe", "M1").upper() != "M1":
        raise ValueError("Este robô está configurado exclusivamente para timeframe M1.")
    if settings.get("trade_type", "binary").lower() != "binary":
        raise ValueError("Este robô está bloqueado para operar somente opções BINÁRIAS.")

    candidates = []
    analyzed_count = 0
    excluded_keys = excluded_keys or set()
    for asset in assets:
        analyzed_count += 1
        try:
            candles = connector.get_candles(
                asset["symbol"], 60, int(settings.get("candles_count", 250))
            )
            if len(candles) < 21:
                continue

            provisional = get_intrabar_signal(candles, settings)
            if not provisional:
                continue
            signal_ts = normalize_timestamp(candles[-1].get("timestamp"))
            server_ts = normalize_timestamp(connector.get_server_timestamp())
            if signal_ts is None or server_ts is None:
                continue
            seconds_remaining = signal_ts + 60 - server_ts
            if is_candle_still_open(seconds_remaining):
                candidate = {
                    **asset,
                    **provisional,
                    "timeframe": "M1",
                    "expiry_minutes": 1,
                    "signal_timestamp": candles[-1].get("timestamp"),
                    "close_timestamp": signal_ts + 60,
                    "stage": "WAIT_NEXT_OPEN",
                }
                key = "{}|{}|{}".format(
                    candidate.get("symbol"), candidate.get("direction"),
                    candidate.get("signal_timestamp")
                )
                if key in excluded_keys:
                    continue
                candidates.append(candidate)
                logging.info(
                    "PRIMEIRO SINAL DETECTADO | %s %s | próxima abertura M1 às %.0f",
                    candidate["symbol"], candidate["direction"], candidate["close_timestamp"]
                )
                return candidates
        except ConnectionError:
            raise
        except Exception as exc:
            if is_transport_error(exc):
                connector.connected = False
                raise ConnectionError("Conexão interrompida durante a leitura de candles.") from exc
            logging.warning("Falha ao analisar %s: %s", asset["symbol"], exc)

    candidates = candidates[:max_candidates]
    logging.info("VARREDURA %d: %d ativos analisados; %d sinais encontrados (limite %d).",
                 _scan_pass_number, analyzed_count, len(candidates), max_candidates)
    return candidates


def find_candle_index_by_timestamp(candles, target_timestamp):
    """Localiza a vela pelo timestamp, sem presumir que a API inclua a vela em formação."""
    target = normalize_timestamp(target_timestamp)
    if target is None:
        return None
    for index, candle in enumerate(candles):
        if normalize_timestamp(candle.get("timestamp")) == target:
            return index
    return None


def verify_closed_signal(connector, settings, candidate):
    """Confirma a própria vela do sinal, esteja ela no fim ou penúltima na resposta da API."""
    candles = connector.get_candles(
        candidate["symbol"], 60, int(settings.get("candles_count", 250))
    )
    if len(candles) < 22:
        return None

    target_timestamp = normalize_timestamp(candidate.get("signal_timestamp"))
    close_timestamp = normalize_timestamp(candidate.get("close_timestamp"))
    if target_timestamp is None or close_timestamp is None:
        return None

    # O timestamp de abertura, sozinho, não prova que a vela fechou:
    # algumas respostas da API incluem a vela ainda em formação como último item.
    # Consulta o relógio da corretora para distinguir esse caso do histórico
    # que retorna somente velas concluídas.
    server_timestamp = normalize_timestamp(connector.get_server_timestamp())
    if server_timestamp is None or server_timestamp < close_timestamp:
        return None

    target_index = find_candle_index_by_timestamp(candles, candidate.get("signal_timestamp"))
    if target_index is None:
        latest_timestamp = normalize_timestamp(candles[-1].get("timestamp"))
        if latest_timestamp is not None and latest_timestamp > target_timestamp:
            return False
        return None

    # O chamador só chega aqui depois do horário de fechamento da vela.
    # Calculamos o cruzamento exatamente no candle que gerou o pré-sinal.
    confirmed = get_signal_at_index(candles, target_index)
    if not confirmed or confirmed.get("direction") != candidate.get("direction"):
        return False
    return {
        **candidate,
        **confirmed,
        "symbol": candidate["symbol"],
        "active_id": candidate["active_id"],
        "signal_timestamp": candidate["signal_timestamp"],
        "timeframe": "M1",
        "expiry_minutes": 1,
        "closed_signal_verified": True,
        "signal_close_timestamp": close_timestamp,
    }


def validate_signal_immediately_before_order(connector, settings, candidate):
    """Faz somente a checagem de relógio final; não repete consultas pesadas de candles."""
    if not candidate.get("closed_signal_verified"):
        return False, "a vela do sinal ainda não foi confirmada como fechada"

    close_ts = normalize_timestamp(candidate.get("signal_close_timestamp", candidate.get("close_timestamp")))
    if close_ts is None:
        return False, "timestamp de fechamento do sinal inválido"

    # A confirmação técnica da vela já ocorreu em verify_closed_signal.
    # Aqui fazemos somente a última checagem do relógio, imediatamente antes
    # de place_practice_order, sem baixar o histórico de candles novamente.
    server_now = normalize_timestamp(connector.get_server_timestamp())
    if server_now is None:
        return False, "relógio da corretora indisponível"

    elapsed = server_now - close_ts
    if not is_next_candle_entry_window(
        elapsed, ENTRY_CONFIRMATION_TOLERANCE_SECONDS, 60.0
    ):
        if elapsed < 0:
            return False, "a vela do sinal ainda não fechou"
        if elapsed >= 60.0:
            return False, "a vela imediatamente seguinte já passou; entrada descartada"
        return False, "tolerância de 3 segundos excedida; entrada descartada"

    return True, "mesma vela do sinal confirmada; ordem autorizada na primeira vela seguinte"


def candidate_key(candidate):
    return "{}|{}|{}".format(
        candidate.get("symbol"),
        candidate.get("direction"),
        candidate.get("signal_timestamp"),
    )


def main():
    # A trava é liberada pelo sistema operacional quando o processo termina.
    # Isso impede duas instâncias, mesmo se Termux e Telegram enviarem /start juntos.
    robot_lock = acquire_robot_lock()
    if robot_lock is None:
        print("DEMEX já está em execução nesta pasta. Nenhuma segunda instância será iniciada.", flush=True)
        return

    # Um pedido de parada só deve afetar uma sessão já iniciada. Se o arquivo
    # sobrou de uma sessão anterior, consumi-lo aqui evita que o próximo
    # comando "python main.py" conecte e encerre imediatamente.
    if STOP_FILE.exists():
        try:
            STOP_FILE.unlink()
            logging.warning("Pedido de parada antigo removido; iniciando uma nova sessão.")
        except OSError as exc:
            raise RuntimeError("Não foi possível limpar o pedido de parada antigo: {}".format(exc))

    load_dotenv()
    settings = load_settings()
    trading = settings.get("trading", {})
    if not trading.get("automatic_execution_enabled", False):
        raise RuntimeError("Execução automática desabilitada em settings.json.")
    if trading.get("mode") != "DEMO":
        raise RuntimeError("Este robô foi configurado exclusivamente para DEMO.")

    cfg = BullexConfig.from_env()
    if cfg.account_type != "PRACTICE":
        raise RuntimeError("BULLEX_ACCOUNT_TYPE deve ser PRACTICE. REAL é bloqueado.")

    connector = BullexReadOnlyConnector(cfg)
    try:
        status = connector.connect()
        if not status.get("connected"):
            print("Conexão inicial indisponível. O DEMEX ficará tentando reconectar...")
            connector.reconnect_forever(stop_check=STOP_FILE.exists)
        print(json.dumps({"connected": True, "account_type": "PRACTICE"},
                         ensure_ascii=False, indent=2))
        if connector.client.get_balance_mode() != "PRACTICE":
            raise PermissionError("Conta ativa não é PRACTICE. Nenhuma ordem será enviada.")

        assets = get_market_assets(connector, settings, stop_check=STOP_FILE.exists)
        next_asset_refresh = time.monotonic() + ASSET_REFRESH_INTERVAL_SECONDS
        trader = DemoTrader(connector, settings, stop_check=STOP_FILE.exists)
        telegram = TelegramNotifier.from_env()
        print(
            "DEMEX AUTOMÁTICO iniciado em PRACTICE/DEMO | BINÁRIAS | M1 | expiração 1 minuto | "
            "SCRIPT GO 2024 | SMA 1/34 + WMA 5 | filtros EMA 21 e EMA 45 | confirmação no fechamento e entrada na próxima vela M1."
            
        )
        print(
            "Ativos OTC disponíveis: {} | Atualização a cada 15 minutos | "
            "Entrada R$ {:.2f} | Soros 1 | Stop R$ {:.2f} | Take R$ {:.2f}"
            .format(len(assets), trader.base, trader.stop, trader.take)
        )
        telegram.send_session_start(
            account="PRACTICE/DEMO", market=settings.get("market_mode", "OTC"),
            timeframe="M1", expiry_minutes=trader.expiry, assets_count=len(assets),
            initial_entry=trader.base, stop_loss=trader.stop, take_profit=trader.take
        )

        # Apenas o primeiro sinal encontrado aguarda a próxima abertura M1.
        pending = {}
        processed = set()

        while not trader.stopped:
            if STOP_FILE.exists():
                trader.stopped = True
                print("PARADA SOLICITADA: nenhuma nova operação será iniciada.")
                break

            if not pending and time.monotonic() >= next_asset_refresh:
                try:
                    assets = get_market_assets(connector, settings, stop_check=STOP_FILE.exists)
                    logging.info(
                        "LISTA OTC ATUALIZADA: %d ativos disponíveis para análise.",
                        len(assets)
                    )
                    next_asset_refresh = time.monotonic() + ASSET_REFRESH_INTERVAL_SECONDS
                except ConnectionError as exc:
                    logging.warning("Conexão perdida ao atualizar ativos OTC: %s", exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    next_asset_refresh = 0.0
                except Exception as exc:
                    logging.error(
                        "Disponibilidade OTC não confirmada; análise pausada: %s", exc
                    )
                    assets = []
                    next_asset_refresh = time.monotonic() + ASSET_REFRESH_INTERVAL_SECONDS

            try:
                if pending:
                    candidates = []
                else:
                    candidates = scan_once(
                        connector, settings, assets,
                        max_candidates=MAX_PENDING_SIGNALS,
                        excluded_keys=set(processed)
                    )
            except ConnectionError as exc:
                logging.warning("Conexão perdida durante a análise: %s", exc)
                connector.reconnect_forever(stop_check=STOP_FILE.exists)
                assets = []
                pending.clear()
                next_asset_refresh = 0.0
                continue

            if STOP_FILE.exists():
                trader.stopped = True
                print("PARADA SOLICITADA: sinais descartados; nenhuma nova operação será iniciada.")
                break

            for candidate in candidates:
                key = candidate_key(candidate)
                if key in processed or key in pending:
                    continue
                if len(pending) < MAX_PENDING_SIGNALS:
                    pending[key] = candidate
                    logging.info(
                        "SINAL DETECTADO | %s %s | aguardando somente a abertura da próxima vela %s",
                        candidate["symbol"], candidate["direction"], candidate["close_timestamp"]
                    )

            try:
                server_now = normalize_timestamp(connector.get_server_timestamp())
            except ConnectionError as exc:
                logging.warning("Conexão perdida ao consultar o relógio da corretora: %s", exc)
                connector.reconnect_forever(stop_check=STOP_FILE.exists)
                assets = []
                pending.clear()
                next_asset_refresh = 0.0
                continue
            except Exception as exc:
                logging.warning("Não foi possível ler o relógio da corretora: %s", exc)
                time.sleep(0.10 if pending else scan_delay(settings))
                continue

            ready = []
            for key, candidate in list(pending.items()):
                close_ts = normalize_timestamp(candidate.get("close_timestamp"))
                if server_now is None or close_ts is None:
                    pending.pop(key, None)
                    processed.add(key)
                    continue
                elapsed = server_now - close_ts
                if elapsed < 0:
                    continue
                if not is_close_confirmation_tolerance(elapsed, ENTRY_CONFIRMATION_TOLERANCE_SECONDS):
                    logging.info(
                        "SINAL CANCELADO: %s %s | %.2fs após o fechamento; tolerância máxima excedida.",
                        candidate["symbol"], candidate["direction"], elapsed
                    )
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                # Confirma o sinal na própria vela que o originou. A ordem
                # só poderá ser enviada na vela imediatamente seguinte.
                try:
                    confirmed = verify_closed_signal(connector, settings, candidate)
                except ConnectionError as exc:
                    logging.warning("Conexão perdida ao revalidar sinal: %s", exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    next_asset_refresh = 0.0
                    ready = []
                    break
                except Exception as exc:
                    if is_transport_error(exc):
                        connector.connected = False
                        logging.warning("Conexão perdida ao revalidar sinal: %s", exc)
                        connector.reconnect_forever(stop_check=STOP_FILE.exists)
                        assets = []
                        pending.clear()
                        next_asset_refresh = 0.0
                        ready = []
                        break
                    logging.warning(
                        "Não foi possível revalidar %s na abertura: %s",
                        candidate["symbol"], exc
                    )
                    continue

                if confirmed is None:
                    # A corretora ainda não publicou a vela fechada do sinal.
                    # Aguarda apenas dentro da janela de 3s; depois o sinal expira.
                    continue
                if confirmed is False:
                    logging.info(
                        "SINAL CANCELADO POR REPINTURA: %s %s | "
                        "não permaneceu válido na abertura da próxima vela.",
                        candidate["symbol"], candidate["direction"]
                    )
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                candidate = confirmed
                ready.append((close_ts, key, candidate))
                break

            if ready:
                _, selected_key, candidate = ready[0]
                logging.info(
                    "SINAL CONFIRMADO | %s %s | %.2fs após o fechamento; envio restrito à primeira vela seguinte.",
                    candidate["symbol"], candidate["direction"], server_now - close_ts
                )
                pending.pop(selected_key, None)
                processed.add(selected_key)

                try:
                    if STOP_FILE.exists():
                        trader.stopped = True
                        break
                    def final_order_check():
                        # Executado dentro do gerenciador, depois da confirmação
                        # PRACTICE e imediatamente antes do envio da ordem.
                        try:
                            still_valid, validation_reason = validate_signal_immediately_before_order(
                                connector, settings, candidate
                            )
                        except Exception as exc:
                            if is_transport_error(exc):
                                connector.connected = False
                                raise ConnectionError(
                                    "Conexão perdida na validação final do sinal."
                                ) from exc
                            logging.warning(
                                "ENTRADA CANCELADA | %s %s | falha na validação final: %s",
                                candidate["symbol"], candidate["direction"], exc
                            )
                            return False

                        if not still_valid:
                            logging.info(
                                "ENTRADA CANCELADA | %s %s | %s. "
                                "DEMEX continuará procurando novos sinais.",
                                candidate["symbol"], candidate["direction"], validation_reason
                            )
                            return False

                        logging.info(
                            "VALIDAÇÃO FINAL APROVADA | %s %s | %s",
                            candidate["symbol"], candidate["direction"], validation_reason
                        )
                        message = (
                            "SINAL {} | {} | M1 | entrada somente nos primeiros 3 segundos da vela imediatamente seguinte | expiração 1 minuto"
                            .format(candidate["symbol"], candidate["direction"])
                        )
                        alert(message, bool(settings.get("sound_alert", True)))
                        print("Confirmações: " + ", ".join(candidate.get("reasons", [])))
                        return True

                    summary = trader.execute_and_settle(
                        candidate, pre_order_check=final_order_check
                    )
                    if summary:
                        print(
                            "PLACAR | Entradas {} | WIN {} | LOSS {} | TIE {} | "
                            "Aproveitamento {:.2f}% | P&L R$ {:+.2f}".format(
                                summary["total_entries"], summary["wins"], summary["losses"],
                                summary["ties"], summary["win_rate"], summary["session_net"]
                            )
                        )
                        print(
                            "OPERAÇÃO {} | {} {} | Entrada R$ {:.2f} | "
                            "Próxima entrada R$ {:.2f}".format(
                                summary["result"], summary["symbol"], summary["direction"],
                                summary["entry"], summary["next_entry"]
                            )
                        )
                        telegram.send_trade_result(summary)
                        if summary["stopped"]:
                            print("ROBÔ ENCERRADO: " + str(summary["stop_reason"]))
                except ConnectionError as exc:
                    logging.warning("Conexão perdida antes da ordem: %s", exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    next_asset_refresh = 0.0
                except OrderRejectedError as exc:
                    # Recusa explícita: não houve abertura; não contabiliza resultado
                    # e mantém o DEMEX analisando outros sinais.
                    logging.warning(
                        "ORDEM RECUSADA PELA CORRETORA | %s %s | %s. "
                        "Nenhuma entrada contabilizada; DEMEX continuará analisando.",
                        candidate["symbol"], candidate["direction"], exc
                    )
                except OrderConfirmationUnknownError as exc:
                    # Sem ID, o estado é incerto. Parar evita duplicidade e falsa perda.
                    logging.critical(
                        "CONFIRMAÇÃO DA ORDEM DESCONHECIDA | %s %s | %s. "
                        "Sessão pausada por segurança; confira o histórico da BullX.",
                        candidate["symbol"], candidate["direction"], exc
                    )
                    trader.stopped = True
                    trader.stop_reason = "Confirmação da ordem desconhecida; verificar histórico da BullX"
                except RuntimeError as exc:
                    error_text = str(exc).lower()
                    if (
                        "cannot purchase an option (the asset is not available at the moment)"
                        in error_text
                        or "cannot purchase an option (active is suspended)" in error_text
                    ):
                        logging.warning("Ativo %s indisponível/suspenso: %s",
                                        candidate["symbol"], exc)
                    else:
                        logging.exception("Falha na execução; robô interrompido por segurança.")
                        trader.stopped = True
                except Exception:
                    logging.exception("Falha na execução/resultado; robô interrompido por segurança.")
                    trader.stopped = True
            else:
                # Se o sinal foi expirado/cancelado, volta imediatamente à varredura.
                # Mantém a pausa curta somente enquanto aguarda a vela; se não houver
                # ativos (ex.: reconexão/atualização), respeita o intervalo configurado.
                if pending:
                    time.sleep(0.10)
                elif assets:
                    continue
                else:
                    time.sleep(scan_delay(settings))

        if trader.stopped:
            print("Sessão encerrada. Resultado líquido: R$ %.2f" % trader.net)
            telegram.send_session_end(
                reason=getattr(trader, "stop_reason", None) or "Sessão encerrada",
                total_entries=trader.total_entries, wins=trader.wins, losses=trader.losses,
                ties=trader.ties, session_net=trader.net
            )
    except InterruptedError as exc:
        print("Parada solicitada: encerrando o DEMEX com segurança. {}".format(exc), flush=True)
        trader_instance = locals().get("trader")
        telegram_instance = locals().get("telegram")
        if trader_instance is not None:
            trader_instance.stopped = True
        if trader_instance is not None and telegram_instance is not None:
            try:
                telegram_instance.send_session_end(
                    reason="Parada solicitada durante a reconexão",
                    total_entries=trader_instance.total_entries,
                    wins=trader_instance.wins,
                    losses=trader_instance.losses,
                    ties=trader_instance.ties,
                    session_net=trader_instance.net,
                )
            except Exception:
                logging.exception("Não foi possível enviar a confirmação final ao Telegram.")
    except KeyboardInterrupt:
        print("\\nInterrupção recebida no Termux. Registrando o encerramento no Telegram.", flush=True)
        trader_instance = locals().get("trader")
        telegram_instance = locals().get("telegram")
        if trader_instance is not None and telegram_instance is not None:
            try:
                telegram_instance.send_session_end(
                    reason="Interrupção recebida pelo Termux (Ctrl+C)",
                    total_entries=trader_instance.total_entries,
                    wins=trader_instance.wins,
                    losses=trader_instance.losses,
                    ties=trader_instance.ties,
                    session_net=trader_instance.net,
                )
            except Exception:
                logging.exception("Não foi possível enviar a confirmação de encerramento ao Telegram.")
    finally:
        connector.close()


if __name__ == "__main__":
    main()
