"""DEMEX automatic signal trader — PRACTICE/DEMO only."""
import json, logging, subprocess, time, threading
from pathlib import Path
from dotenv import load_dotenv
from bullex_connector import BullexConfig, BullexReadOnlyConnector
from signal_engine import analyze
from strategies.my_strategy import get_pre_signal
from trade_manager import DemoTrader
from backtest_filter import evaluate_backtest

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s: %(message)s")

# Sinal de parada solicitado pelo comando demex.sh parar.
STOP_FILE = Path(".demex_stop")
_priority_symbols = []
_scan_cycle = 0
_approved_assets = []
_approved_lock = threading.RLock()
_refresh_stop = threading.Event()


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

def signal_is_in_next_candle(connector, signal):
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
    # Janela estrita: somente os primeiros 5 segundos da vela M1 vizinha.
    entry_deadline=next_candle_start+5.0
    if not (next_candle_start <= server_ts < entry_deadline):
        logging.info(
            "Sinal %s descartado por atraso: candle do sinal=%d, janela de entrada=[%.3f,%.3f), servidor=%.3f.",
            signal.get("symbol","?"),int(signal_ts),next_candle_start,entry_deadline,server_ts
        )
        return False
    return True

def refresh_approved_assets(connector, settings):
    """Backtesta os ultimos 100 candles M1 dos ativos com payout binario >=84%."""
    global _approved_assets
    minimum_trades = int(settings.get("backtest_min_trades", 5))
    market_mode = settings.get("market_mode", "OTC")
    min_payout = float(settings.get("minimum_payout_percent", 84))
    max_payout = float(settings.get("maximum_payout_percent", 100))
    assets = connector.get_open_assets(min_payout, max_payout)
    assets = [a for a in assets if market_matches(a["symbol"], market_mode)]
    approved = []
    logging.info("BACKTEST: avaliando %d ativos com payout binario entre %.1f%% e %.1f%%; janela de 100 candles M1.",
                 len(assets), min_payout, max_payout)
    for index, asset in enumerate(assets, 1):
        if _refresh_stop.is_set():
            break
        try:
            candles = connector.get_candles(
                asset["symbol"], 60, int(settings.get("backtest_candles", 100)) + 1
            )
            result = evaluate_backtest(candles, minimum_trades)
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
    approved.sort(key=lambda a: (a["backtest"]["win_rate"],
                                 a["backtest"]["trades"],
                                 a["payout_percent"]), reverse=True)
    with _approved_lock:
        _approved_assets = approved
    logging.info("BACKTEST CONCLUIDO: %d/%d ativos aprovados (minimo %d operacoes historicas e acerto >70%%).",
                 len(approved), len(assets), minimum_trades)
    return approved


def refresh_worker(connector, settings):
    """Atualiza a lista aprovada a cada 30 minutos sem parar o loop de sinais."""
    while not _refresh_stop.wait(1800):
        try:
            refresh_approved_assets(connector, settings)
        except Exception as exc:
            logging.exception("Falha na atualizacao do backtest; mantendo a ultima lista aprovada: %s", exc)


def scan_once(connector,settings):
    global _priority_symbols, _scan_cycle
    _scan_cycle += 1
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
        logging.info("Nenhum ativo aprovado no backtest atual. Aguardando a proxima atualizacao.")
        return []
    logging.info("Ativos liberados pelo backtest: %d | payout binario >=84%% | acerto historico >70%%.",
                 len(assets))
    priority_rank={symbol:index for index,symbol in enumerate(_priority_symbols)}
    # Todos os ativos dentro da faixa continuam sendo observados; pré-sinais só alteram a ordem.
    assets.sort(key=lambda item: priority_rank.get(item["symbol"],len(priority_rank)+1))
    candidates=[]
    pre_signals=[]
    # A estratégia AHORA precisa de 17 candles; 40 dão margem sem baixar 250
    # candles em cada ativo a cada ciclo. O histórico de backtest continua em 100.
    scan_candle_count=max(30,min(40,int(settings.get("candles_count",120))))
    # Um único horário de referência por ciclo evita uma chamada de relógio por ativo.
    scan_server_time=connector.get_server_timestamp()
    for asset in assets:
        try:
            candles=connector.get_candles(
                asset["symbol"],seconds,scan_candle_count,
                server_timestamp=scan_server_time
            )
            pre=get_pre_signal(candles,settings)
            if pre:
                pre_signals.append({**pre,**asset})
            # O gatilho é calculado exclusivamente na última vela já fechada.
            result=analyze(candles,settings)
            if not result: continue
            signal_ts=candles[-2].get("timestamp")
            candidate={**result,**asset,"timeframe":tf,"expiry_minutes":expiry,"signal_timestamp":signal_ts}
            # Descarta sinais cuja janela da vela seguinte já venceu AQUI,
            # antes de retornar ao executor. Assim um sinal antigo de um ativo
            # não bloqueia a procura por sinais ainda válidos nos outros aprovados.
            # O executor repete a checagem imediatamente antes do envio da ordem.
            if not signal_is_in_next_candle(connector,candidate):
                continue
            _priority_symbols=list(dict.fromkeys([asset["symbol"]]+[item["symbol"] for item in pre_signals]))
            logging.info("SINAL CONFIRMADO E DENTRO DA JANELA: %s em %s; aguardando envio na vela M1 seguinte (janela máxima de 5s).",result["direction"],asset["symbol"])
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
    # Sem confluência confirmada, conservar a fila de pré-sinais para o próximo ciclo.
    candidates.sort(key=lambda item: (item["confidence"], item["payout_percent"]), reverse=True)
    return candidates

def main():
    refresh_thread=None
    load_dotenv()
    settings=load_settings()
    # Uma resposta buy() sem ID é ambígua: pode existir ordem aberta na corretora.
    # Não iniciar outra sessão até a conferência manual do histórico PRACTICE.
    pending_order=Path(".demex_pending_order.json")
    if pending_order.exists():
        print("ROBÔ BLOQUEADO: existe uma submissão de ordem sem confirmação.")
        print("Confira o histórico da conta PRACTICE e os dados em .demex_pending_order.json.")
        print("Não apague o bloqueio nem reinicie o robô antes de reconciliar a operação.")
        return
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
                        # O sinal já foi calculado sobre a vela fechada recebida na varredura.
                        # Não fazer uma segunda consulta de candles: ela consome a janela de entrada.
                        # Entrada somente na vela M1 imediatamente seguinte, até 5s após abrir.
                        if not signal_is_in_next_candle(connector,candidate):
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
