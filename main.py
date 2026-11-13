"""DEMEX automatic signal trader — PRACTICE/DEMO only."""
import json
import logging
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from bullex_connector import (
    BullexConfig, BullexReadOnlyConnector, MarketDataUnavailableError,
    is_transport_error,
    OrderRejectedError, OrderConfirmationUnknownError,
)
from strategies.my_strategy import get_intrabar_signal, get_signal_at_index  # GO 2024 SUPER
from trade_manager import DemoTrader
from telegram_notifier import TelegramNotifier
from robot_lock import acquire_robot_lock
from asset_selector import select_qualified_assets
from entry_timing import (
    filter_market_assets,
    is_candle_still_open,
    is_close_confirmation_tolerance,
    is_next_candle_entry_window,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

STOP_FILE = Path(".demex_stop")
ASSET_REFRESH_INTERVAL_SECONDS = 900
ENTRY_CONFIRMATION_TOLERANCE_SECONDS = 5.0


def asset_refresh_interval(settings):
    """Intervalo entre ciclos completos de disponibilidade + backtest OTC."""
    try:
        configured = int(settings.get("asset_refresh_interval_seconds", ASSET_REFRESH_INTERVAL_SECONDS))
    except (TypeError, ValueError):
        configured = ASSET_REFRESH_INTERVAL_SECONDS
    return max(60, configured)
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


def _wait_for_market_data_retry(delay, stop_check=None):
    """Espera em pequenos intervalos para permitir /stop durante falhas da API."""
    deadline = time.monotonic() + max(0.0, float(delay))
    while True:
        if stop_check and stop_check():
            raise InterruptedError("Parada solicitada durante a atualização dos ativos OTC.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.25, remaining))


def get_market_assets(connector, settings, stop_check=None):
    """Retorna ativos OTC do tipo compatível com a expiração configurada."""
    mode = str(settings.get("market_mode", "OTC")).upper()
    if mode != "OTC":
        raise RuntimeError("Este robô está configurado para analisar exclusivamente ativos OTC.")

    retry_delay = 5
    while True:
        if stop_check and stop_check():
            raise InterruptedError("Parada solicitada durante a atualização dos ativos OTC.")
        try:
            availability = connector.get_otc_asset_availability(
                expiry_minutes=int(settings.get("expiry_minutes", 1))
            )
            if not availability:
                raise MarketDataUnavailableError(
                    "A BullX retornou zero ativos OTC; a lista não será considerada válida."
                )
            break
        except MarketDataUnavailableError as exc:
            logging.warning(
                "BullX ainda não forneceu a lista de ativos OTC (%s). "
                "Nova consulta em %d segundos; nenhuma operação será liberada.",
                exc, retry_delay
            )
            _wait_for_market_data_retry(retry_delay, stop_check=stop_check)
            retry_delay = min(retry_delay * 2, 30)
        except Exception as exc:
            if not is_transport_error(exc):
                raise
            connector.connected = False
            logging.warning("Conexão perdida ao atualizar ativos OTC: %s", exc)
            connector.reconnect_forever(stop_check=stop_check)
            retry_delay = 5

    available = [
        {"symbol": item["symbol"], "active_id": item["active_id"]}
        for item in availability if item.get("available") is True
    ]
    unavailable_count = len(availability) - len(available)
    option_types = sorted({str(item.get("option_type", "indefinido")).upper() for item in availability})
    logging.info(
        "TIPO DE CONTRATO OTC CONFORME EXPIRAÇÃO: %s.",
        ", ".join(option_types) if option_types else "não identificado"
    )
    logging.info(
        "DISPONIBILIDADE OTC: %d disponíveis; %d fechados ou suspensos. "
        "Atualização a cada %d minutos.",
        len(available), unavailable_count, asset_refresh_interval(settings) // 60
    )
    return filter_market_assets(available, "OTC")


def scan_once(connector, settings, assets, max_candidates=1, excluded_keys=None):
    """Procura padrões em velas fechadas e libera entrada só na vela M1 seguinte."""
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
            if len(candles) < 45:
                continue

            try:
                server_ts = normalize_timestamp(connector.get_server_timestamp())
            except Exception as exc:
                if is_transport_error(exc):
                    connector.connected = False
                    raise ConnectionError("Conexão interrompida ao consultar o relógio da corretora.") from exc
                raise
            if server_ts is None:
                continue

            # A API pode incluir ou omitir a vela em formação. Encontra a
            # vela mais recente cujo fechamento já foi confirmado pelo relógio.
            signal_index = None
            close_ts = None
            for index in range(len(candles) - 1, -1, -1):
                candle_ts = normalize_timestamp(candles[index].get("timestamp"))
                if candle_ts is None:
                    continue
                candle_close_ts = candle_ts + 60.0
                elapsed = server_ts - candle_close_ts
                if elapsed >= 0:
                    if elapsed <= ENTRY_CONFIRMATION_TOLERANCE_SECONDS:
                        signal_index, close_ts = index, candle_close_ts
                    break
            if signal_index is None:
                continue

            signal = get_signal_at_index(candles, signal_index)
            if not signal:
                continue

            candidate = {
                **asset,
                **signal,
                "timeframe": "M1",
                "expiry_minutes": 1,
                "signal_timestamp": candles[signal_index].get("timestamp"),
                "close_timestamp": close_ts,
                "detected_at_server_timestamp": close_ts,
                "stage": "CLOSED_NEXT_CANDLE_ENTRY",
            }
            key = "{}|{}|{}".format(
                candidate.get("symbol"), candidate.get("direction"),
                candidate.get("signal_timestamp")
            )
            if key in excluded_keys:
                continue
            candidates.append(candidate)
            logging.info(
                "SINAL EM VELA FECHADA | %s %s | entrada na próxima M1, fechamento %.0f",
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
    if len(candles) < 45:
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


def verify_intrabar_signal(connector, settings, candidate):
    """Validador legado de sinais intrabar; não é usado no fluxo principal."""
    candles = connector.get_candles(
        candidate["symbol"], 60, int(settings.get("candles_count", 250))
    )
    if len(candles) < 45:
        return None

    target_timestamp = normalize_timestamp(candidate.get("signal_timestamp"))
    close_timestamp = normalize_timestamp(candidate.get("close_timestamp"))
    detected_at = normalize_timestamp(candidate.get("detected_at_server_timestamp"))
    server_now = normalize_timestamp(connector.get_server_timestamp())
    if None in (target_timestamp, close_timestamp, detected_at, server_now):
        return None

    elapsed_since_detection = server_now - detected_at
    if elapsed_since_detection < 0 or elapsed_since_detection > ENTRY_CONFIRMATION_TOLERANCE_SECONDS:
        return False
    if server_now >= close_timestamp:
        return False

    target_index = find_candle_index_by_timestamp(candles, candidate.get("signal_timestamp"))
    # A vela do sinal precisa continuar sendo a vela atual/em formação.
    if target_index is None or target_index != len(candles) - 1:
        return False

    current_signal = get_intrabar_signal(candles, settings)
    if not current_signal or current_signal.get("direction") != candidate.get("direction"):
        return False

    return {
        **candidate,
        **current_signal,
        "symbol": candidate["symbol"],
        "active_id": candidate["active_id"],
        "signal_timestamp": candidate["signal_timestamp"],
        "close_timestamp": candidate["close_timestamp"],
        "detected_at_server_timestamp": detected_at,
        "timeframe": "M1",
        "expiry_minutes": 1,
        "intrabar_signal_verified": True,
    }


def validate_intrabar_signal_immediately_before_order(connector, settings, candidate):
    """Validador legado: autoriza a vela atual dentro da tolerância configurada."""
    if not candidate.get("intrabar_signal_verified"):
        return False, "sinal intrabar ainda não confirmado"

    try:
        verified = verify_intrabar_signal(connector, settings, candidate)
    except Exception:
        raise

    if verified is None:
        return False, "não foi possível confirmar a vela atual e o relógio da corretora"
    if verified is False:
        return False, "sinal expirado, alterado ou fora da tolerância de 3 segundos"

    return True, "sinal confirmado na própria vela; envio dentro de 3 segundos da detecção"


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
        return False, "tolerância de 5 segundos excedida; entrada descartada"

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

        available_assets = get_market_assets(connector, settings, stop_check=STOP_FILE.exists)
        if settings.get("backtest_enabled", True):
            assets, backtest_report = select_qualified_assets(
                connector, available_assets, settings, stop_check=STOP_FILE.exists
            )
        else:
            assets, backtest_report = available_assets, []
            logging.info(
                "BACKTEST DESATIVADO | %d ativos OTC disponíveis liberados diretamente para a varredura de sinais.",
                len(assets)
            )
        refresh_interval = asset_refresh_interval(settings)
        next_asset_refresh = time.monotonic() + refresh_interval
        trader = DemoTrader(connector, settings, stop_check=STOP_FILE.exists)
        telegram = TelegramNotifier.from_env()
        trader.late_settlement_callback = telegram.send_trade_result
        print(
            "DEMEX AUTOMÁTICO iniciado em PRACTICE/DEMO | OPÇÕES M1 (TURBO conforme API BullX) | expiração 1 minuto | "
            "INDICADOR HARAMI + ENGOLFO | padrões originais + filtros EMA 21/45 | sem cruzamento SMA/WMA adicional | confirmação no fechamento e entrada na próxima M1 (até 5s)."
            
        )
        selection_label = (
            "Backtest desativado; todos os disponíveis liberados"
            if not settings.get("backtest_enabled", True)
            else "Aprovados no backtest: {}".format(len(assets))
        )
        print(
            "Ativos OTC disponíveis: {} | {} | atualização da lista a cada {} minutos | "
            "Entrada R$ {:.2f} | Soros 1 | Stop R$ {:.2f} | Take R$ {:.2f}"
            .format(
                len(available_assets), selection_label, refresh_interval // 60,
                trader.base, trader.stop, trader.take
            )
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
                    available_assets = get_market_assets(
                        connector, settings, stop_check=STOP_FILE.exists
                    )
                    if settings.get("backtest_enabled", True):
                        assets, backtest_report = select_qualified_assets(
                            connector, available_assets, settings, stop_check=STOP_FILE.exists
                        )
                        logging.info(
                            "LISTA OTC SUBSTITUÍDA APÓS NOVO BACKTEST: %d disponíveis; "
                            "%d aprovados para sinais e entradas.",
                            len(available_assets), len(assets)
                        )
                    else:
                        assets = available_assets
                        backtest_report = []
                        logging.info(
                            "LISTA OTC ATUALIZADA SEM BACKTEST: %d ativos disponíveis liberados para sinais.",
                            len(assets)
                        )
                    next_asset_refresh = time.monotonic() + refresh_interval
                except ConnectionError as exc:
                    logging.warning("Conexão perdida ao atualizar ativos OTC: %s", exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    next_asset_refresh = 0.0
                except Exception as exc:
                    if is_transport_error(exc):
                        connector.connected = False
                        logging.warning(
                            "Falha transitória de rede ao atualizar ativos OTC: %s. "
                            "DEMEX aguardará a reconexão.",
                            exc
                        )
                        connector.reconnect_forever(stop_check=STOP_FILE.exists)
                        assets = []
                        pending.clear()
                        next_asset_refresh = 0.0
                        continue
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
                        "SINAL DETECTADO | %s %s | fechamento previsto %.0f",
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
                if is_transport_error(exc):
                    connector.connected = False
                    logging.warning(
                        "Falha transitória de rede ao consultar o relógio da BullX: %s. "
                        "DEMEX aguardará a reconexão e descartará sinais antigos.",
                        exc
                    )
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    next_asset_refresh = 0.0
                    continue
                logging.warning("Não foi possível ler o relógio da corretora: %s", exc)
                time.sleep(0.10 if pending else scan_delay(settings))
                continue

            ready = []
            for key, candidate in list(pending.items()):
                detected_at = normalize_timestamp(candidate.get("detected_at_server_timestamp"))
                if server_now is None or detected_at is None:
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                elapsed = server_now - detected_at
                if elapsed < 0:
                    continue
                if elapsed > ENTRY_CONFIRMATION_TOLERANCE_SECONDS:
                    logging.info(
                        "SINAL CANCELADO: %s %s | %.2fs após o fechamento; "
                        "janela máxima de 5 segundos da próxima M1 excedida.",
                        candidate["symbol"], candidate["direction"], elapsed
                    )
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                # Confirma o padrão na vela já fechada; a ordem só pode sair
                # dentro dos primeiros 5 segundos da vela imediatamente seguinte.
                try:
                    confirmed = verify_closed_signal(connector, settings, candidate)
                except ConnectionError as exc:
                    logging.warning("Conexão perdida ao revalidar sinal fechado: %s", exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    next_asset_refresh = 0.0
                    ready = []
                    break
                except Exception as exc:
                    if is_transport_error(exc):
                        connector.connected = False
                        logging.warning("Conexão perdida ao revalidar sinal fechado: %s", exc)
                        connector.reconnect_forever(stop_check=STOP_FILE.exists)
                        assets = []
                        pending.clear()
                        next_asset_refresh = 0.0
                        ready = []
                        break
                    logging.warning(
                        "Não foi possível confirmar a vela fechada de %s: %s",
                        candidate["symbol"], exc
                    )
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                if confirmed is None:
                    continue
                if confirmed is False:
                    logging.info(
                        "SINAL CANCELADO: %s %s | padrão ou filtros EMA não confirmados "
                        "na vela fechada.",
                        candidate["symbol"], candidate["direction"]
                    )
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                candidate = confirmed
                ready.append((detected_at, key, candidate))
                break

            if ready:
                detected_at, selected_key, candidate = ready[0]
                logging.info(
                    "SINAL FECHADO CONFIRMADO | %s %s | %.2fs após o fechamento; "
                    "entrada na próxima vela M1.",
                    candidate["symbol"], candidate["direction"], server_now - detected_at
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
                            "SINAL {} | {} | M1 | entrada nos primeiros 5 segundos da próxima vela após o fechamento | expiração 1 minuto"
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
                            "Aproveitamento {:.2f}% | Seq. WIN {} | Seq. LOSS {} | "
                            "Recorde WIN {} | Recorde LOSS {} | P&L R$ {:+.2f}".format(
                                summary["total_entries"], summary["wins"], summary["losses"],
                                summary["ties"], summary["win_rate"],
                                summary["current_win_streak"], summary["current_loss_streak"],
                                summary["max_win_streak"], summary["max_loss_streak"],
                                summary["session_net"]
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
                    # O gerenciador monitora o request_id original e libera a próxima
                    # entrada após a expiração M1, sem reenviar a ordem anterior.
                    logging.critical(
                        "CONFIRMAÇÃO DA ORDEM DESCONHECIDA | %s %s | %s. "
                        "A resposta será reconciliada em segundo plano; após 1 minuto "
                        "o DEMEX poderá procurar a próxima entrada.",
                        candidate["symbol"], candidate["direction"], exc
                    )
                except PermissionError:
                    # Conta diferente de PRACTICE ou outra trava de segurança:
                    # não tentar contornar nem continuar enviando ordens.
                    logging.exception("Trava de segurança da conta acionada; sessão encerrada.")
                    trader.stopped = True
                    trader.stop_reason = "Trava de segurança da conta PRACTICE"
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
                        logging.exception(
                            "Resposta inesperada da BullX durante a execução. "
                            "DEMEX vai reconectar e retomar sem encerrar a sessão."
                        )
                        connector.connected = False
                        connector.reconnect_forever(stop_check=STOP_FILE.exists)
                        assets = []
                        pending.clear()
                        next_asset_refresh = 0.0
                except Exception as exc:
                    logging.exception(
                        "Falha inesperada (%s). DEMEX vai reconectar e retomar a análise; "
                        "nenhuma ordem será repetida automaticamente.",
                        exc
                    )
                    connector.connected = False
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    next_asset_refresh = 0.0
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
