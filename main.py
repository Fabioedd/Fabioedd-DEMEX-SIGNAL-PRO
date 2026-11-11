"""DEMEX automatic signal trader — PRACTICE/DEMO only."""
import json
import logging
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from bullex_connector import BullexConfig, BullexReadOnlyConnector
from strategies.my_strategy import get_intrabar_signal, get_signal, backtest_strategy
from trade_manager import DemoTrader
from telegram_notifier import TelegramNotifier
from entry_timing import (
    can_add_pending_signal,
    filter_market_assets,
    is_candle_still_open,
    is_close_confirmation_window,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

STOP_FILE = Path(".demex_stop")
ASSET_REFRESH_INTERVAL_SECONDS = 300
MAX_PENDING_SIGNALS = 2
ENTRY_CONFIRMATION_SECONDS = 5.0
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


def get_market_assets(connector, settings):
    """Retorna somente ativos OTC binários que a corretora informa disponíveis."""
    mode = str(settings.get("market_mode", "OTC")).upper()
    if mode != "OTC":
        raise RuntimeError("Este robô está configurado para analisar exclusivamente ativos OTC.")
    availability = connector.get_otc_asset_availability()
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


def scan_once(connector, settings, assets, max_candidates=MAX_PENDING_SIGNALS, excluded_keys=None):
    """Detecta pré-sinais na vela M1 atual; nunca envia ordens nesta etapa."""
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
            if len(candles) < 17:
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
                    "stage": "PENDING_CLOSE",
                    "_backtest_candles": candles,
                }
                key = "{}|{}|{}".format(
                    candidate.get("symbol"), candidate.get("direction"),
                    candidate.get("signal_timestamp")
                )
                if key in excluded_keys:
                    continue
                candidates.append(candidate)
                if len(candidates) >= max_candidates:
                    logging.info("LIMITE DE %d sinais pendentes atingido; pausando a varredura.", max_candidates)
                    break
        except ConnectionError:
            raise
        except Exception as exc:
            logging.warning("Falha ao analisar %s: %s", asset["symbol"], exc)

    logging.info(
        "VARREDURA %d: %d ativos analisados; %d pré-sinais encontrados.",
        _scan_pass_number, analyzed_count, len(candidates)
    )
    return candidates


def verify_closed_signal(connector, settings, candidate):
    """Confirma o mesmo sinal na vela já fechada, usando a estratégia original."""
    candles = connector.get_candles(
        candidate["symbol"], 60, int(settings.get("candles_count", 250))
    )
    if len(candles) < 17:
        return None

    # get_signal avalia candles[:-1], ou seja, a última vela concluída.
    closed_timestamp = normalize_timestamp(candles[-2].get("timestamp"))
    target_timestamp = normalize_timestamp(candidate.get("signal_timestamp"))
    if closed_timestamp is None or target_timestamp is None:
        return None
    if closed_timestamp != target_timestamp:
        return None

    confirmed = get_signal(candles, settings)
    if not confirmed or confirmed.get("direction") != candidate.get("direction"):
        return None
    return {
        **candidate,
        **confirmed,
        "symbol": candidate["symbol"],
        "active_id": candidate["active_id"],
        "signal_timestamp": candidate["signal_timestamp"],
        "timeframe": "M1",
        "expiry_minutes": 1,
    }


def candidate_key(candidate):
    return "{}|{}|{}".format(
        candidate.get("symbol"),
        candidate.get("direction"),
        candidate.get("signal_timestamp"),
    )


def main():
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

        assets = get_market_assets(connector, settings)
        next_asset_refresh = time.monotonic() + ASSET_REFRESH_INTERVAL_SECONDS
        trader = DemoTrader(connector, settings)
        telegram = TelegramNotifier.from_env()
        print(
            "DEMEX AUTOMÁTICO iniciado em PRACTICE/DEMO | BINÁRIAS | M1 | expiração 1 minuto | "
            "SCRIPT AHORA RSI EXHAUSTION | RSI({}) | backtest histórico para desempate dos dois pendentes | sem filtro de payout."
            .format(settings.get("rsi_period", 14))
        )
        print(
            "Ativos OTC disponíveis: {} | Atualização a cada 5 minutos | "
            "Entrada R$ {:.2f} | Soros 1 | Stop R$ {:.2f} | Take R$ {:.2f}"
            .format(len(assets), trader.base, trader.stop, trader.take)
        )
        telegram.send_session_start(
            account="PRACTICE/DEMO", market=settings.get("market_mode", "OTC"),
            timeframe="M1", expiry_minutes=trader.expiry, assets_count=len(assets),
            initial_entry=trader.base, stop_loss=trader.stop, take_profit=trader.take
        )

        # No máximo dois ativos ficam pendentes; com dois, a varredura é pausada.
        pending = {}
        processed = set()
        preferred_key = None

        while not trader.stopped:
            if STOP_FILE.exists():
                trader.stopped = True
                print("PARADA SOLICITADA: nenhuma nova operação será iniciada.")
                break

            if len(pending) < MAX_PENDING_SIGNALS and time.monotonic() >= next_asset_refresh:
                try:
                    assets = get_market_assets(connector, settings)
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
                    preferred_key = None
                    next_asset_refresh = 0.0
                except Exception as exc:
                    logging.error(
                        "Disponibilidade OTC não confirmada; análise pausada: %s", exc
                    )
                    assets = []
                    next_asset_refresh = time.monotonic() + ASSET_REFRESH_INTERVAL_SECONDS

            try:
                if len(pending) >= MAX_PENDING_SIGNALS:
                    logging.info("DOIS ATIVOS PENDENTES: varredura pausada; acompanhando somente os dois sinais.")
                    candidates = []
                else:
                    candidates = scan_once(
                        connector, settings, assets,
                        max_candidates=MAX_PENDING_SIGNALS - len(pending),
                        excluded_keys=set(pending)
                    )
            except ConnectionError as exc:
                logging.warning("Conexão perdida durante a análise: %s", exc)
                connector.reconnect_forever(stop_check=STOP_FILE.exists)
                assets = []
                pending.clear()
                preferred_key = None
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
                if can_add_pending_signal(len(pending), MAX_PENDING_SIGNALS):
                    pending[key] = candidate
                    logging.info(
                        "PRÉ-SINAL AGUARDANDO FECHAMENTO: %s %s | vela %s",
                        candidate["symbol"], candidate["direction"],
                        candidate["signal_timestamp"]
                    )

            # Se uma pendência caiu, a próxima dupla será comparada novamente.
            if len(pending) < MAX_PENDING_SIGNALS:
                preferred_key = None

            # Assim que o segundo sinal entra, compara os dois usando o histórico
            # de candles_count (250 por configuração), sem alterar a estratégia.
            if len(pending) == MAX_PENDING_SIGNALS and preferred_key is None:
                for pending_key, pending_candidate in pending.items():
                    if "backtest" in pending_candidate:
                        continue
                    stats = backtest_strategy(
                        pending_candidate.pop("_backtest_candles", []), settings
                    )
                    pending_candidate["backtest"] = stats
                    logging.info(
                        "BACKTEST %s: %d sinais | %d WIN | %d LOSS | %d TIE | assertividade %.2f%%",
                        pending_candidate["symbol"], stats["signals"], stats["wins"],
                        stats["losses"], stats["ties"], stats["accuracy"]
                    )
                preferred_key = max(
                    pending,
                    key=lambda item: (
                        pending[item].get("backtest", {}).get("accuracy", 0.0),
                        -normalize_timestamp(pending[item].get("close_timestamp") or 0)
                    )
                )
                logging.info(
                    "PREFERÊNCIA PELO BACKTEST: %s | assertividade %.2f%%",
                    pending[preferred_key]["symbol"],
                    pending[preferred_key].get("backtest", {}).get("accuracy", 0.0)
                )

            try:
                server_now = normalize_timestamp(connector.get_server_timestamp())
            except ConnectionError as exc:
                logging.warning("Conexão perdida ao consultar o relógio da corretora: %s", exc)
                connector.reconnect_forever(stop_check=STOP_FILE.exists)
                assets = []
                pending.clear()
                preferred_key = None
                next_asset_refresh = 0.0
                continue
            except Exception as exc:
                logging.warning("Não foi possível ler o relógio da corretora: %s", exc)
                time.sleep(0.25 if len(pending) >= MAX_PENDING_SIGNALS else scan_delay(settings))
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
                if not is_close_confirmation_window(elapsed, ENTRY_CONFIRMATION_SECONDS):
                    logging.info(
                        "SINAL EXPIRADO: %s %s | %.2fs após o fechamento.",
                        candidate["symbol"], candidate["direction"], elapsed
                    )
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                try:
                    confirmed = verify_closed_signal(connector, settings, candidate)
                except ConnectionError as exc:
                    logging.warning("Conexão perdida ao confirmar %s: %s", candidate["symbol"], exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    preferred_key = None
                    next_asset_refresh = 0.0
                    break
                if not confirmed:
                    logging.info(
                        "SINAL DESCARTADO: não confirmou no fechamento | %s %s.",
                        candidate["symbol"], candidate["direction"]
                    )
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                # A confirmação da API pode consumir tempo; confira novamente
                # imediatamente antes de autorizar a ordem.
                try:
                    final_now = normalize_timestamp(connector.get_server_timestamp())
                except ConnectionError as exc:
                    logging.warning(
                        "Conexão perdida na confirmação final do sinal: %s", exc
                    )
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    pending.clear()
                    preferred_key = None
                    next_asset_refresh = 0.0
                    break
                final_elapsed = final_now - close_ts if final_now is not None else None
                if final_elapsed is None or not is_close_confirmation_window(
                    final_elapsed, ENTRY_CONFIRMATION_SECONDS
                ):
                    logging.info(
                        "SINAL EXPIRADO DURANTE A CONFIRMAÇÃO: %s %s.",
                        candidate["symbol"], candidate["direction"]
                    )
                    pending.pop(key, None)
                    processed.add(key)
                    continue

                ready.append((close_ts, key, confirmed))

            # Se o ativo preferido ainda está aguardando seu fechamento, não
            # antecipamos a entrada no segundo. Se o preferido for descartado,
            # o segundo passa a ser a alternativa, desde que sua janela siga válida.
            if preferred_key not in pending:
                preferred_key = None
                if pending:
                    preferred_key = max(
                        pending,
                        key=lambda item: pending[item].get("backtest", {}).get("accuracy", 0.0)
                    )
            ready_by_key = {item[1]: item for item in ready}
            if preferred_key in ready_by_key:
                _, selected_key, candidate = ready_by_key[preferred_key]
                logging.info(
                    "ENTRADA AUTORIZADA PELO BACKTEST: %s %s | assertividade histórica %.2f%%.",
                    candidate["symbol"], candidate["direction"],
                    candidate.get("backtest", {}).get("accuracy", 0.0)
                )
                for other_key in list(pending):
                    if other_key != selected_key:
                        processed.add(other_key)
                    pending.pop(other_key, None)
                processed.add(selected_key)
                preferred_key = None

                try:
                    if STOP_FILE.exists():
                        trader.stopped = True
                        break
                    message = (
                        "SINAL CONFIRMADO {} | {} | M1 | RSI {:.2f} | expiração 1 minuto"
                        .format(candidate["symbol"], candidate["direction"],
                                float(candidate.get("rsi") or 0.0))
                    )
                    alert(message, bool(settings.get("sound_alert", True)))
                    print("Confirmações: " + ", ".join(candidate.get("reasons", [])))
                    summary = trader.execute_and_settle(candidate)
                    if summary:
                        print(
                            "PLACAR | Entradas {} | WIN {} | LOSS {} | TIE {} | "
                            "Aproveitamento {:.2f}% | P&L R$ {:+.2f}".format(
                                summary["total_entries"], summary["wins"], summary["losses"],
                                summary["ties"], summary["win_rate"], summary["session_net"]
                            )
                        )
                        print(
                            "OPERAÇÃO {} | {} {} | Entrada R$ {:.2f} | Resultado R$ {:+.2f} | "
                            "Próxima entrada R$ {:.2f}".format(
                                summary["result"], summary["symbol"], summary["direction"],
                                summary["entry"], summary["pnl"], summary["next_entry"]
                            )
                        )
                        telegram.send_trade_result(summary)
                        if summary["stopped"]:
                            print("ROBÔ ENCERRADO: " + str(summary["stop_reason"]))
                except ConnectionError as exc:
                    logging.warning("Conexão perdida antes da ordem: %s", exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    next_asset_refresh = 0.0
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
                # Enquanto há pendências, acompanha os candles sem iniciar outra
                # varredura completa. A varredura normal continua em 2 segundos.
                time.sleep(0.25 if len(pending) >= MAX_PENDING_SIGNALS else scan_delay(settings))

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
        print("\\nRobô encerrado pelo usuário.")
    finally:
        connector.close()


if __name__ == "__main__":
    main()
