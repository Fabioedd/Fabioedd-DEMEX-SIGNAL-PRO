"""DEMEX automatic signal trader — PRACTICE/DEMO only."""
import json
import logging
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from bullex_connector import BullexConfig, BullexReadOnlyConnector
from strategies.my_strategy import get_intrabar_signal
from trade_manager import DemoTrader
from telegram_notifier import TelegramNotifier
from entry_timing import filter_market_assets, is_candle_still_open, is_intrabar_entry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

STOP_FILE = Path(".demex_stop")
ASSET_REFRESH_INTERVAL_SECONDS = 300
_scan_pass_number = 0


def scan_delay(settings):
    """Intervalo normal entre varreduras, limitado a 1–3 segundos."""
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
    ts = float(value)
    return ts / 1000.0 if ts > 10_000_000_000 else ts


def get_market_assets(connector, settings):
    """Retorna somente OTC BINÁRIOS que a corretora informa estarem abertos."""
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
        "DISPONIBILIDADE OTC: %d abertos/disponíveis; %d fechados ou suspensos. "
        "A lista será atualizada a cada %d minutos.",
        len(available), unavailable_count, ASSET_REFRESH_INTERVAL_SECONDS // 60
    )
    return available


def scan_once(connector, settings, assets):
    """Analisa todos os ativos e devolve sinais sem bloquear a varredura."""
    global _scan_pass_number
    _scan_pass_number += 1
    if settings.get("timeframe", "M1").upper() != "M1":
        raise ValueError("Este robô está configurado exclusivamente para timeframe M1.")
    if settings.get("trade_type", "binary").lower() != "binary":
        raise ValueError("Este robô está bloqueado para operar somente opções BINÁRIAS.")

    settings["timeframe"] = "M1"
    settings["expiry_minutes"] = 1
    candidates = []
    for asset in assets:
        try:
            candles = connector.get_candles(
                asset["symbol"], 60, int(settings.get("candles_count", 250))
            )
            if len(candles) < 17:
                continue

            # Primeiro registra o pré-sinal da vela atual, sem enviar ordem.
            provisional = get_intrabar_signal(candles, settings)
            if provisional:
                signal_ts = normalize_timestamp(candles[-1].get("timestamp"))
                if signal_ts is not None:
                    server_ts = normalize_timestamp(connector.get_server_timestamp())
                    seconds_remaining = signal_ts + 60 - server_ts
                    if is_candle_still_open(seconds_remaining):
                        candidates.append({
                            **provisional, **asset, "timeframe": "M1",
                            "expiry_minutes": 1,
                            "signal_timestamp": candles[-1].get("timestamp"),
                            "stage": "INTRABAR",
                        })
                        continue

        except ConnectionError:
            raise
        except Exception as exc:
            logging.warning("Falha ao analisar %s: %s", asset["symbol"], exc)

    logging.info(
        "VARREDURA %d: %d ativos analisados; %d sinais encontrados.",
        _scan_pass_number, len(assets), len(candidates)
    )
    return candidates

def wait_until(connector, target_timestamp):
    """Espera usando o relógio da corretora; respeita pedido de parada."""
    while not STOP_FILE.exists():
        now = normalize_timestamp(connector.get_server_timestamp())
        if now >= target_timestamp:
            return now
        time.sleep(min(0.15, max(0.02, target_timestamp - now)))
    return None


def verify_intrabar(connector, settings, candidate):
    candles = connector.get_candles(
        candidate["symbol"], 60, int(settings.get("candles_count", 250))
    )
    if not candles:
        return False
    current_ts = normalize_timestamp(candles[-1].get("timestamp"))
    original_ts = normalize_timestamp(candidate.get("signal_timestamp"))
    if current_ts != original_ts:
        return False
    current = get_intrabar_signal(candles, settings)
    return bool(current and current.get("direction") == candidate.get("direction"))


def verify_closed(connector, settings, candidate):
    candles = connector.get_candles(
        candidate["symbol"], 60, int(settings.get("candles_count", 250))
    )
    if len(candles) < 2:
        return False
    closed_ts = normalize_timestamp(candles[-2].get("timestamp"))
    original_ts = normalize_timestamp(candidate.get("signal_timestamp"))
    if closed_ts != original_ts:
        return False
    current = analyze(candles, settings)
    return bool(current and current.get("direction") == candidate.get("direction"))


def verify_closed(connector, settings, candidate):
    """Confirma que o mesmo sinal continua presente na vela M1 já encerrada."""
    candles = connector.get_candles(
        candidate["symbol"], 60, int(settings.get("candles_count", 250))
    )
    if len(candles) < 2:
        return False
    current_ts = normalize_timestamp(candles[-1].get("timestamp"))
    closed_ts = normalize_timestamp(candles[-2].get("timestamp"))
    original_ts = normalize_timestamp(candidate.get("signal_timestamp"))
    # Só valida depois que a corretora publicou uma vela posterior à vela do sinal.
    if current_ts is None or closed_ts is None or original_ts is None:
        return False
    if current_ts <= original_ts or closed_ts != original_ts:
        return False
    elapsed = normalize_timestamp(connector.get_server_timestamp()) - (original_ts + 60)
    if not is_close_confirmation_window(elapsed):
        return False
    current = analyze(candles, settings)
    return bool(current and current.get("direction") == candidate.get("direction"))


def candidate_key(candidate):
    return "{}|{}|{}".format(
        candidate.get("symbol"),
        candidate.get("direction"),
        candidate.get("signal_timestamp"),
    )


def candidate_close_timestamp(candidate):
    signal_ts = normalize_timestamp(candidate.get("signal_timestamp"))
    return None if signal_ts is None else signal_ts + 60


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
            "SCRIPT AHORA RSI EXHAUSTION | RSI({}) | sem payout/backtest/varredura de 30 minutos."
            .format(settings.get("rsi_period", 14))
        )
        print("Ativos OTC disponíveis: {} | Atualização a cada 5 minutos | Entrada R$ {:.2f} | Soros 1 | Stop R$ {:.2f} | Take R$ {:.2f}"
              .format(len(assets), trader.base, trader.stop, trader.take))
        telegram.send_session_start(
            account="PRACTICE/DEMO", market=settings.get("market_mode", "OTC"),
            timeframe="M1", expiry_minutes=trader.expiry, assets_count=len(assets),
            initial_entry=trader.base, stop_loss=trader.stop, take_profit=trader.take
        )

        # Cada sinal intrabar é processado uma única vez, na vela em formação.
        processed = set()

        while not trader.stopped:
            if STOP_FILE.exists():
                trader.stopped = True
                print("PARADA SOLICITADA: nenhuma nova operação será iniciada.")
                break
            if time.monotonic() >= next_asset_refresh:
                try:
                    assets = get_market_assets(connector, settings)
                    logging.info("LISTA OTC ATUALIZADA: %d ativos disponíveis para análise.", len(assets))
                    next_asset_refresh = time.monotonic() + ASSET_REFRESH_INTERVAL_SECONDS
                except ConnectionError as exc:
                    logging.warning("Conexão perdida durante a atualização dos ativos OTC: %s", exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
                    assets = []
                    next_asset_refresh = 0.0
                except Exception as exc:
                    # Falha na leitura: não usa uma lista possivelmente desatualizada.
                    logging.error("Não foi possível confirmar a disponibilidade OTC; análise pausada: %s", exc)
                    assets = []
                    next_asset_refresh = time.monotonic() + ASSET_REFRESH_INTERVAL_SECONDS
            try:
                candidates = scan_once(connector, settings, assets)
            except ConnectionError as exc:
                logging.warning("Conexão perdida durante a análise: %s", exc)
                connector.reconnect_forever(stop_check=STOP_FILE.exists)
                assets = []
                next_asset_refresh = 0.0
                continue

            if STOP_FILE.exists():
                trader.stopped = True
                print("PARADA SOLICITADA: sinais descartados; nenhuma nova operação será iniciada.")
                break

            confirmed = []
            # Executa o sinal assim que ele é detectado na vela M1 ainda aberta.
            # Não aguarda fechamento, confirmação posterior nem entrada na vela seguinte.
            for candidate in candidates:
                key = candidate_key(candidate)
                if key in processed or not is_intrabar_entry(candidate.get("stage")):
                    continue
                processed.add(key)
                confirmed.append(candidate)
                logging.info(
                    "SINAL INTRABAR DETECTADO: %s %s; entrada imediata na vela atual.",
                    candidate["symbol"], candidate["direction"]
                )

            if confirmed:
                # Uma única entrada: escolhe o sinal confirmado mais antigo; os demais são descartados.
                confirmed.sort(key=lambda item: normalize_timestamp(item["signal_timestamp"]) or 0)
                candidate = confirmed[0]
                for item in confirmed[1:]:
                    processed.add(candidate_key(item))
                logging.info(
                    "SELEÇÃO ÚNICA: %s %s. Outros sinais confirmados não serão operados.",
                    candidate["symbol"], candidate["direction"]
                )
                try:
                    if STOP_FILE.exists():
                        trader.stopped = True
                        break
                    message = (
                        "SINAL {} | {} | M1 | RSI {:.2f} | expiração 1 minuto"
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
                    if ("cannot purchase an option (the asset is not available at the moment)" in error_text
                            or "cannot purchase an option (active is suspended)" in error_text):
                        logging.warning("Ativo %s indisponível/suspenso: %s",
                                        candidate["symbol"], exc)
                    else:
                        logging.exception("Falha na execução; robô interrompido por segurança.")
                        trader.stopped = True
                except Exception:
                    logging.exception("Falha na execução/resultado; robô interrompido por segurança.")
                    trader.stopped = True
            else:
                time.sleep(scan_delay(settings))

        if trader.stopped:
            print("Sessão encerrada. Resultado líquido: R$ %.2f" % trader.net)
            telegram.send_session_end(
                reason=getattr(trader, "stop_reason", None) or "Sessão encerrada",
                total_entries=trader.total_entries, wins=trader.wins, losses=trader.losses,
                ties=trader.ties, session_net=trader.net
            )
    except KeyboardInterrupt:
        print("\\nRobô encerrado pelo usuário.")
    finally:
        connector.close()


if __name__ == "__main__":
    main()
