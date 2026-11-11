"""DEMEX automatic signal trader — PRACTICE/DEMO only."""
import json, logging, subprocess, time, threading
from pathlib import Path
from dotenv import load_dotenv
from bullex_connector import BullexConfig, BullexReadOnlyConnector
from signal_engine import analyze
from strategies.my_strategy import get_pre_signal, get_intrabar_signal
from trade_manager import DemoTrader
from backtest_filter import evaluate_backtest

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s: %(message)s")

# Sinal de parada solicitado pelo comando demex.sh parar.
STOP_FILE = Path(".demex_stop")
_priority_symbols = []
_scan_cycle = 0
_approved_assets = []
_pending_intrabar_signals = {}
_approved_lock = threading.RLock()
_refresh_stop = threading.Event()
_scan_pass_number = 0


def scan_delay(settings):
    """Intervalo de varredura limitado a 1–3 segundos."""
    return max(1, min(3, int(settings.get("scan_interval_seconds", 2))))

def load_settings():
    with open("settings.json",encoding="utf-8") as f: return json.load(f)

def alert(message,enabled=True):
    print("\\a"+message,flush=True)
    if enabled:
        try: subprocess.Popen(["termux-tts-speak",message])
        except (FileNotFoundError,OSError): pass

def market_matches(symbol,mode):
    otc="OTC" in symbol.upper()
    return otc if mode.upper()=="OTC" else not otc

def signal_is_in_next_candle(connector, signal, settings):
    """Só autoriza a entrada durante a M1 imediatamente posterior ao candle do sinal."""
    raw_ts=signal.get("signal_timestamp")
    if raw_ts is None:
        logging.warning("Sinal %s descartado: timestamp do candle não disponível.",signal.get("symbol","?"))
        return False
    try:
        signal_ts=float(raw_ts)
        server_ts=float(connector.get_server_timestamp())
    except (TypeError,ValueError,AttributeError) as exc:
        logging.error("Não foi possível validar o horário do sinal: %s",exc)
        raise RuntimeError("Horário do servidor/candle inválido; entrada bloqueada.") from exc

    # Algumas APIs podem devolver timestamps em milissegundos.
    if signal_ts > 10_000_000_000:
        signal_ts /= 1000.0
    if server_ts > 10_000_000_000:
        server_ts /= 1000.0

    next_candle_start=signal_ts+60
    # Janela estrita: somente os primeiros 10 segundos da vela M1 vizinha.
    entry_deadline=next_candle_start+float(settings.get("entry_confirmation_window_seconds",10))
    if not (next_candle_start <= server_ts < entry_deadline):
        logging.info(
            "Sinal %s descartado por atraso: candle do sinal=%d, janela de entrada=[%.3f,%.3f), servidor=%.3f.",
            signal.get("symbol","?"),int(signal_ts),next_candle_start,entry_deadline,server_ts
        )
        return False
    return True

def normalize_timestamp(value):
    """Converte timestamp Unix em segundos, aceitando também milissegundos."""
    if value is None:
        return None
    ts=float(value)
    return ts / 1000.0 if ts > 10_000_000_000 else ts


def resolve_intrabar_confirmation(pending, symbol, closed_timestamp, closed_signal):
    """Só libera o sinal intrabar se a mesma direção sobreviver ao fechamento."""
    provisional = pending.get(symbol)
    if provisional is None:
        return closed_signal

    provisional_ts = normalize_timestamp(provisional.get("timestamp"))
    closed_ts = normalize_timestamp(closed_timestamp)
    if provisional_ts is None or closed_ts is None or provisional_ts > closed_ts:
        return closed_signal

    pending.pop(symbol, None)
    if provisional_ts != closed_ts:
        return closed_signal

    if not closed_signal or closed_signal.get("direction") != provisional.get("direction"):
        logging.info(
            "SINAL PROVISÓRIO %s CANCELADO: não permaneceu igual após o fechamento da vela.",
            symbol
        )
        return None

    logging.info(
        "SINAL PROVISÓRIO %s %s CONFIRMADO no fechamento da vela.",
        symbol, provisional.get("direction")
    )
    return closed_signal


def signal_still_present(connector, settings, candidate):
    """Reconsulta o ativo e exige o mesmo sinal na mesma vela fechada."""
    symbol=candidate["symbol"]
    try:
        candles=connector.get_candles(
            symbol,60,int(settings.get("candles_count",250))
        )
        if len(candles) < 2:
            logging.info("Sinal %s descartado: candles insuficientes na rechecagem.",symbol)
            return False

        latest_closed_ts=normalize_timestamp(candles[-2].get("timestamp"))
        original_ts=normalize_timestamp(candidate.get("signal_timestamp"))
        if latest_closed_ts is None or original_ts is None or latest_closed_ts != original_ts:
            logging.info(
                "Sinal %s descartado: a vela fechada mudou desde a detecção "
                "(original=%s, atual=%s).",
                symbol,original_ts,latest_closed_ts
            )
            return False

        current=analyze(candles,settings)
        if (not current
                or current.get("direction") != candidate.get("direction")
                or current.get("confidence",0) < settings["minimum_confidence"]):
            logging.info(
                "Sinal %s descartado: não permanece confirmado na rechecagem.",
                symbol
            )
            return False

        candidate.update(current)
        candidate["signal_timestamp"]=candles[-2].get("timestamp")
        logging.info(
            "Sinal %s %s CONFIRMADO novamente na mesma vela fechada.",
            symbol,candidate["direction"]
        )
        return True
    except ConnectionError:
        raise
    except Exception as exc:
        logging.warning("Sinal %s descartado: falha na rechecagem: %s",symbol,exc)
        return False




def refresh_approved_assets(connector, settings):
    """Backtesta os ultimos 100 candles M1 dos ativos com payout binario >=84%."""
    global _approved_assets
    market_mode = settings.get("market_mode", "OTC")
    min_payout = float(settings.get("minimum_payout_percent", 84))
    max_payout = float(settings.get("maximum_payout_percent", 100))
    assets = connector.get_open_assets(min_payout, max_payout)
    assets = [a for a in assets if market_matches(a["symbol"], market_mode)]
    approved = []
    completed = not _refresh_stop.is_set()
    logging.info("BACKTEST: avaliando %d ativos com payout binario entre %.1f%% e %.1f%%; janela de 100 candles M1.",
                 len(assets), min_payout, max_payout)
    for index, asset in enumerate(assets, 1):
        if _refresh_stop.is_set():
            completed = False
            break
        try:
            candles = connector.get_candles(
                asset["symbol"], 60, int(settings.get("backtest_candles", 100)) + 1
            )
            result = evaluate_backtest(candles)
            logging.info("BACKTEST %d/%d | %s | payout %.1f%% | sinais %d | WIN %d | LOSS %d | acerto %.2f%% | %s",
                         index, len(assets), asset["symbol"], asset["payout_percent"],
                         result["trades"], result["wins"], result["losses"],
                         result["win_rate"], result["reason"])
            if result["approved"]:
                approved.append({**asset, "backtest": result})
        except ConnectionError:
            raise
        except Exception as exc:
            logging.warning("BACKTEST ignorou %s: %s", asset["symbol"], exc)
    if _refresh_stop.is_set():
        completed = False
    approved.sort(key=lambda a: (a["backtest"]["win_rate"],
                                 a["backtest"]["trades"],
                                 a["payout_percent"]), reverse=True)
    # Uma varredura completa sempre substitui a lista, inclusive por [].
    # Se a varredura foi interrompida, preserva a lista ativa anterior.
    with _approved_lock:
        if completed:
            _approved_assets = approved
            active_assets = list(_approved_assets)
            if active_assets:
                logging.info("LISTA APROVADA SUBSTITUIDA: %d ativos.", len(active_assets))
            else:
                logging.warning("VARREDURA COMPLETA SEM APROVADOS: lista ativa zerada; nenhum ativo sera monitorado.")
        else:
            active_assets = list(_approved_assets)
            logging.warning(
                "BACKTEST INTERROMPIDO: mantendo os %d ativos da lista anterior; resultado parcial descartado.",
                len(active_assets)
            )
    if completed:
        logging.info("BACKTEST CONCLUIDO: %d/%d ativos aprovados nesta rodada (assertividade >70%% e payout binario >=84%%; sem minimo de operacoes historicas). Lista ativa: %d.",
                     len(approved), len(assets), len(active_assets))
    else:
        logging.warning("BACKTEST NAO CONCLUIDO; lista ativa inalterada com %d ativos.",len(active_assets))
    return active_assets


def refresh_worker(connector, settings):
    """Refaz o backtest em ciclos de 30 minutos sem interromper a varredura."""
    cycle_seconds = 1800
    while not _refresh_stop.wait(cycle_seconds):
        logging.info("CICLO DE 30 MINUTOS: iniciando novo backtest; o monitoramento continua ativo.")
        try:
            refresh_approved_assets(connector, settings)
        except Exception as exc:
            logging.exception("Falha na atualizacao do backtest; mantendo a ultima lista aprovada: %s", exc)
        logging.info("CICLO DE BACKTEST concluido. Monitoramento segue somente na lista aprovada ativa.")


def scan_once(connector,settings):
    global _priority_symbols, _scan_cycle, _scan_pass_number
    _scan_cycle += 1
    _scan_pass_number += 1
    tf=settings.get("timeframe","M1").upper()
    if tf != "M1": raise ValueError("Este robô está configurado exclusivamente para timeframe M1.")
    if settings.get("trade_type","binary").lower() != "binary":
        raise ValueError("Este robô está bloqueado para operar somente opções BINÁRIAS.")
    seconds=60
    expiry=1
    settings["timeframe"]="M1"
    settings["expiry_minutes"]=1
    settings["minimum_confidence"]=float(settings.get("minimum_confidence",70))
    with _approved_lock:
        assets=list(_approved_assets)
    if not assets:
        logging.warning("VARREDURA %d: lista aprovada vazia. O robô permanece ligado e tentará novamente em %ss; não analisará ativos reprovados.",
                        _scan_pass_number, scan_delay(settings))
        return []
    logging.info("INICIO DA VARREDURA %d: monitorando os %d ativos aprovados (e somente eles) | payout binario >=84%% | acerto historico >70%%.",
                 _scan_pass_number, len(assets))
    priority_rank={symbol:index for index,symbol in enumerate(_priority_symbols)}
    # Todos os ativos dentro da faixa continuam sendo observados; pré-sinais só alteram a ordem.
    assets.sort(key=lambda item: priority_rank.get(item["symbol"],len(priority_rank)+1))
    candidates=[]
    pre_signals=[]
    for asset in assets:
        try:
            candles=connector.get_candles(asset["symbol"],seconds,int(settings.get("candles_count",120)))
            pre=get_pre_signal(candles,settings)
            if pre:
                pre_signals.append({**pre,**asset})

            # Registra o sinal que aparece durante a vela, mas ainda não autoriza entrada.
            provisional=get_intrabar_signal(candles,settings)
            current_ts=normalize_timestamp(candles[-1].get("timestamp")) if candles else None
            if provisional and current_ts is not None:
                previous=_pending_intrabar_signals.get(asset["symbol"])
                if (previous is None
                        or normalize_timestamp(previous.get("timestamp")) != current_ts):
                    _pending_intrabar_signals[asset["symbol"]]={
                        "timestamp":current_ts,
                        "direction":provisional["direction"],
                    }
                    logging.info(
                        "SINAL PROVISÓRIO %s %s detectado durante a vela; aguardando fechamento.",
                        asset["symbol"], provisional["direction"]
                    )

            # O gatilho executável é calculado exclusivamente na última vela já fechada.
            result=analyze(candles,settings)
            closed_ts=normalize_timestamp(candles[-2].get("timestamp")) if len(candles) >= 2 else None
            result=resolve_intrabar_confirmation(
                _pending_intrabar_signals,asset["symbol"],closed_ts,result
            )
            if not result: continue
            signal_ts=candles[-2].get("timestamp")
            candidate={**result,**asset,"timeframe":tf,"expiry_minutes":expiry,"signal_timestamp":signal_ts}
            _priority_symbols=list(dict.fromkeys([asset["symbol"]]+[item["symbol"] for item in pre_signals]))
            logging.info("SINAL CONFIRMADO NA VELA FECHADA: %s em %s; aguardando a próxima vela M1 (janela máxima de 10s).",result["direction"],asset["symbol"])
            return [candidate]
        except ConnectionError:
            raise
        except Exception as exc: logging.warning("Falha ao analisar %s: %s",asset["symbol"],exc)
    pre_signals.sort(key=lambda item: (item["proximity"],item["payout_percent"]), reverse=True)
    _priority_symbols=[item["symbol"] for item in pre_signals]
    if pre_signals:
        preview=", ".join("{} {} ({:.0%})".format(item["symbol"],item["direction"],item["proximity"]) for item in pre_signals[:10])
        logging.info("PRÉ-SINAIS encontrados: %d | Prioridade: %s",len(pre_signals),preview)
    else:
        logging.info("Nenhum pré-sinal ativo nesta varredura.")
    # Chegar ao último ativo sem sinal encerra apenas esta passagem, nunca o robô.
    logging.info("FIM DA VARREDURA %d: %d ativos aprovados percorridos; nenhum sinal válido. Próxima passagem em até %ss, mantendo a mesma lista até o próximo backtest de 30 minutos.",
                 _scan_pass_number, len(assets), scan_delay(settings))
    # Sem confluência confirmada, conservar a fila de pré-sinais para o próximo ciclo.
    candidates.sort(key=lambda item: (item["confidence"], item["payout_percent"]), reverse=True)
    return candidates

def main():
    refresh_thread=None
    load_dotenv()
    settings=load_settings()
    trading=settings.get("trading",{})
    if not trading.get("automatic_execution_enabled",False):
        raise RuntimeError("Execução automática desabilitada em settings.json.")
    if trading.get("mode")!="DEMO":
        raise RuntimeError("Este robô foi configurado exclusivamente para DEMO.")
    cfg=BullexConfig.from_env()
    if cfg.account_type!="PRACTICE":
        raise RuntimeError("BULLEX_ACCOUNT_TYPE deve ser PRACTICE. REAL é bloqueado.")
    connector=BullexReadOnlyConnector(cfg)
    try:
        status=connector.connect()
        if not status.get("connected"):
            print("Conexão inicial indisponível. O DEMEX ficará tentando reconectar...")
            connector.reconnect_forever(stop_check=STOP_FILE.exists)
        print(json.dumps({"connected":True,"account_type":"PRACTICE"},ensure_ascii=False,indent=2))
        if connector.client.get_balance_mode()!="PRACTICE":
            raise PermissionError("Conta ativa não é PRACTICE. Nenhuma ordem será enviada.")
        trader=DemoTrader(connector,settings)
        print("Iniciando backtest dos ultimos 100 candles M1 em todos os ativos com payout binario >=84%...")
        refresh_approved_assets(connector, settings)
        refresh_thread=threading.Thread(target=refresh_worker,args=(connector,settings),daemon=True)
        refresh_thread.start()
        print("DEMEX AUTOMÁTICO iniciado em PRACTICE/DEMO | BINÁRIAS | M1 | expiração 1 minuto | SCRIPT AHORA | payout binário >=84% | backtest >70% a cada 30 minutos.")
        print("Entrada inicial R$ %.2f | Soros 1 | Stop R$ %.2f | Take R$ %.2f" %
              (trader.base,trader.stop,trader.take))
        while not trader.stopped:
            # A parada é cooperativa: nunca interrompe à força uma ordem já enviada.
            if STOP_FILE.exists():
                trader.stopped=True
                print("PARADA SOLICITADA: nenhuma nova operação será iniciada.")
                break
            try:
                signal=scan_once(connector,settings)
            except ConnectionError as exc:
                logging.warning("Conexão perdida durante a análise: %s",exc)
                connector.reconnect_forever(stop_check=STOP_FILE.exists)
                continue
            # Se o pedido chegou durante a varredura, descarta o sinal e não envia ordem.
            if STOP_FILE.exists():
                trader.stopped=True
                print("PARADA SOLICITADA: sinal descartado; nenhuma nova operação será iniciada.")
                break
            if signal:
                order_accepted_or_settled=False
                unavailable_assets=set()
                for candidate in signal:
                    if STOP_FILE.exists():
                        trader.stopped=True
                        print("PARADA SOLICITADA: nenhuma nova operação será iniciada.")
                        break
                    try:
                        # Reconsultar e confirmar o mesmo sinal na mesma vela já fechada.
                        if not signal_still_present(connector,settings,candidate):
                            continue
                        # Entrada somente na vela M1 imediatamente seguinte, até 5s após abrir.
                        if not signal_is_in_next_candle(connector,candidate,settings):
                            continue
                        msg=(f"SINAL {candidate['symbol']} | {candidate['direction']} | {candidate['timeframe']} | "
                             f"expiração {candidate['expiry_minutes']} min | confiança técnica {candidate['confidence']}% | "
                             f"payout {candidate['payout_percent']:.1f}%")
                        alert(msg,bool(settings.get("sound_alert",True)))
                        print("Confirmações: "+", ".join(candidate["reasons"]))
                        summary=trader.execute_and_settle(candidate)
                        if summary:
                            order_accepted_or_settled=True
                            print("PLACAR | Entradas {total_entries} | WIN {wins} | LOSS {losses} | TIE {ties} | "
                                  "Aproveitamento {win_rate:.2f}% | P&L R$ {session_net:+.2f}".format(**summary))
                            print("OPERAÇÃO {result} | {symbol} {direction} | Entrada R$ {entry:.2f} | "
                                  "Resultado R$ {pnl:+.2f} | Próxima entrada R$ {next_entry:.2f}".format(**summary))
                            if summary["stopped"]: print("ROBÔ ENCERRADO: "+str(summary["stop_reason"]))
                            break
                        # Sinal duplicado ou operação não iniciada: não insistir nele.
                    except RuntimeError as exc:
                        error_text=str(exc).lower()
                        if ("cannot purchase an option (the asset is not available at the moment)" in error_text
                                or "cannot purchase an option (active is suspended)" in error_text):
                            unavailable_assets.add(candidate["symbol"])
                            logging.warning(
                                "Ativo %s indisponível/suspenso para entrada (%s). "
                                "Descartando este ativo e procurando o próximo sinal válido...",
                                candidate["symbol"],exc
                            )
                            continue
                        logging.exception("Falha na execução; robô interrompido por segurança.")
                        trader.stopped=True
                        break
                    except Exception:
                        logging.exception("Falha na execução/resultado; robô interrompido por segurança.")
                        trader.stopped=True
                        break
                if not order_accepted_or_settled and not trader.stopped:
                    if unavailable_assets:
                        logging.warning("Todos os %d ativo(s) com sinal testados foram recusados ou não puderam receber ordem. Nova varredura em seguida.",len(unavailable_assets))
                    else:
                        print("Nenhuma ordem iniciada. Aguardando nova varredura...")
                    time.sleep(scan_delay(settings))
            else:
                print("Nenhum sinal qualificado. Aguardando...")
                time.sleep(scan_delay(settings))
        if trader.stopped:
            print("Sessão encerrada. Resultado líquido: R$ %.2f" % trader.net)
    except KeyboardInterrupt:
        print("\\nRobô encerrado pelo usuário.")
    finally:
        _refresh_stop.set()
        if refresh_thread is not None and refresh_thread.is_alive():
            refresh_thread.join(timeout=5)
        connector.close()

if __name__=="__main__": main()
