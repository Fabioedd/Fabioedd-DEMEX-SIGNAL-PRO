"""DEMEX automatic signal trader — PRACTICE/DEMO only."""
import json
import logging
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from bullex_connector import BullexConfig, BullexReadOnlyConnector
from signal_engine import analyze
from strategies.my_strategy import get_intrabar_signal
from trade_manager import DemoTrader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

STOP_FILE = Path(".demex_stop")
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


def market_matches(symbol, mode):
    otc = "OTC" in symbol.upper()
    return otc if mode.upper() == "OTC" else not otc


def normalize_timestamp(value):
    if value is None:
        return None
    ts = float(value)
    return ts / 1000.0 if ts > 10_000_000_000 else ts


def get_market_assets(connector, settings):
    """Carrega os ativos do mercado escolhido sem consultar payout ou backtest."""
    mode = settings.get("market_mode", "OTC")
    assets = [asset for asset in connector.get_assets()
              if market_matches(asset["symbol"], mode)]
    logging.info("ATIVOS CARREGADOS: %d ativos do mercado %s; sem filtro de payout/backtest.",
                 len(assets), mode)
    return assets


def scan_once(connector, settings, assets):
    """Procura sinais SCRIPT AHORA RSI em todos os ativos carregados."""
    global _scan_pass_number
    _scan_pass_number += 1
    if settings.get("timeframe", "M1").upper() != "M1":
        raise ValueError("Este robô está configurado exclusivamente para timeframe M1.")
    if settings.get("trade_type", "binary").lower() != "binary":
        raise ValueError("Este robô está bloqueado para operar somente opções BINÁRIAS.")

    settings["timeframe"] = "M1"
    settings["expiry_minutes"] = 1
    for asset in assets:
        try:
            candles = connector.get_candles(
                asset["symbol"], 60, int(settings.get("candles_count", 250))
            )
            if len(candles) < 17:
                continue

            # Prioridade: sinal na vela em formação, para entrada entre 3 e 2s do fechamento.
            provisional = get_intrabar_signal(candles, settings)
            if provisional:
                signal_ts = normalize_timestamp(candles[-1].get("timestamp"))
                if signal_ts is not None:
                    candidate = {
                        **provisional, **asset, "timeframe": "M1",
                        "expiry_minutes": 1,
                        "signal_timestamp": candles[-1].get("timestamp"),
                    }
                    logging.info(
                        "SINAL INTRABAR %s %s | RSI %.2f | aguardando janela de 3 a 2 segundos antes do fechamento.",
                        asset["symbol"], provisional["direction"], provisional["rsi"]
                    )
                    return candidate

            # Se não houve sinal intrabar, procura sinal na última vela já fechada.
            result = analyze(candles, settings)
            if result:
                closed_ts = normalize_timestamp(candles[-2].get("timestamp"))
                if closed_ts is None:
                    continue
                candidate = {
                    **result, **asset, "timeframe": "M1",
                    "expiry_minutes": 1,
                    "signal_timestamp": candles[-2].get("timestamp"),
                    "stage": "CLOSED",
                }
                logging.info(
                    "SINAL CONFIRMADO NO FECHAMENTO %s %s | aguardando 3 segundos após a abertura da próxima vela.",
                    asset["symbol"], result["direction"]
                )
                return candidate
        except ConnectionError:
            raise
        except Exception as exc:
            logging.warning("Falha ao analisar %s: %s", asset["symbol"], exc)

    logging.info("VARREDURA %d: %d ativos analisados; nenhum sinal válido.",
                 _scan_pass_number, len(assets))
    return None


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


def prepare_entry(connector, settings, candidate):
    """Aplica a janela: 2–3s antes do fechamento, no fechamento ou +3s na vela seguinte."""
    signal_ts = normalize_timestamp(candidate.get("signal_timestamp"))
    if signal_ts is None:
        logging.warning("Sinal descartado: timestamp indisponível.")
        return False

    close_timestamp = signal_ts + 60
    now = normalize_timestamp(connector.get_server_timestamp())
    stage = candidate.get("stage", "CLOSED")

    if stage == "INTRABAR":
        entry_target = close_timestamp - 2.5
        if now < entry_target:
            now = wait_until(connector, entry_target)
            if now is None:
                return False

        # Só entra antes do fechamento se a condição ainda estiver presente na faixa 3–2s.
        if close_timestamp - 3.0 <= now <= close_timestamp - 2.0:
            if verify_intrabar(connector, settings, candidate):
                logging.info("ENTRADA LIBERADA: sinal permanece válido faltando %.2fs para fechar.",
                             close_timestamp - now)
                return True

        # Se a janela antecipada passou, aguarda o fechamento e valida a vela concluída.
        if now < close_timestamp:
            now = wait_until(connector, close_timestamp)
            if now is None:
                return False
        if now <= close_timestamp + 0.75:
            if verify_closed(connector, settings, candidate):
                logging.info("ENTRADA LIBERADA no fechamento da vela M1.")
                return True

        # Se a confirmação só foi capturada já na vela seguinte, aguarda exatamente 3s.
        next_candle_entry = close_timestamp + 3.0
        if now <= next_candle_entry:
            now = wait_until(connector, next_candle_entry)
            if now is None:
                return False
            if verify_closed(connector, settings, candidate):
                logging.info("ENTRADA LIBERADA com 3s de atraso na vela M1 seguinte.")
                return True

        logging.info("Sinal %s cancelado: janela de entrada passou ou condição mudou.",
                     candidate["symbol"])
        return False

    # Sinal percebido somente após o fechamento: aguarda 3s da vela seguinte.
    next_candle_entry = close_timestamp + 3.0
    if now > next_candle_entry:
        logging.info("Sinal %s descartado: detectado depois da janela de 3s da vela seguinte.",
                     candidate["symbol"])
        return False
    now = wait_until(connector, next_candle_entry)
    if now is None:
        return False
    if verify_closed(connector, settings, candidate):
        logging.info("ENTRADA LIBERADA com 3s de atraso após abertura da nova vela.")
        return True
    logging.info("Sinal %s cancelado: não permaneceu válido no fechamento.", candidate["symbol"])
    return False


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
        if not assets:
            raise RuntimeError("Nenhum ativo foi encontrado no mercado configurado.")
        trader = DemoTrader(connector, settings)
        print(
            "DEMEX AUTOMÁTICO iniciado em PRACTICE/DEMO | BINÁRIAS | M1 | expiração 1 minuto | "
            "SCRIPT AHORA RSI EXHAUSTION | RSI({}) | sem payout/backtest/varredura de 30 minutos."
            .format(settings.get("rsi_period", 14))
        )
        print("Ativos monitorados: {} | Entrada R$ {:.2f} | Soros 1 | Stop R$ {:.2f} | Take R$ {:.2f}"
              .format(len(assets), trader.base, trader.stop, trader.take))

        while not trader.stopped:
            if STOP_FILE.exists():
                trader.stopped = True
                print("PARADA SOLICITADA: nenhuma nova operação será iniciada.")
                break
            try:
                candidate = scan_once(connector, settings, assets)
            except ConnectionError as exc:
                logging.warning("Conexão perdida durante a análise: %s", exc)
                connector.reconnect_forever(stop_check=STOP_FILE.exists)
                continue

            if STOP_FILE.exists():
                trader.stopped = True
                print("PARADA SOLICITADA: sinal descartado; nenhuma nova operação será iniciada.")
                break

            if candidate:
                try:
                    if not prepare_entry(connector, settings, candidate):
                        time.sleep(scan_delay(settings))
                        continue
                    if STOP_FILE.exists():
                        trader.stopped = True
                        break
                    message = (
                        "SINAL {} | {} | M1 | RSI {} | expiração 1 minuto"
                        .format(candidate["symbol"], candidate["direction"],
                                candidate.get("rsi", settings.get("rsi_period", 14)))
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
                        if summary["stopped"]:
                            print("ROBÔ ENCERRADO: " + str(summary["stop_reason"]))
                except ConnectionError as exc:
                    logging.warning("Conexão perdida antes da ordem: %s", exc)
                    connector.reconnect_forever(stop_check=STOP_FILE.exists)
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
    except KeyboardInterrupt:
        print("\\nRobô encerrado pelo usuário.")
    finally:
        connector.close()


if __name__ == "__main__":
    main()
