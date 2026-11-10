"""DEMEX automatic signal trader — PRACTICE/DEMO only."""
import json, logging, subprocess, time
from pathlib import Path
from dotenv import load_dotenv
from bullex_connector import BullexConfig, BullexReadOnlyConnector
from signal_engine import analyze
from trade_manager import DemoTrader

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s: %(message)s")

# Sinal de parada solicitado pelo comando demex.sh parar.
STOP_FILE = Path(".demex_stop")


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

def scan_once(connector,settings):
    tf=settings.get("timeframe","M1").upper()
    if tf != "M1": raise ValueError("Este teste do DEMEX está limitado ao timeframe M1.")
    seconds=60
    expiry=1
    settings["timeframe"]="M1"
    settings["expiry_minutes"]=1
    min_payout=float(settings.get("minimum_payout_percent",80))
    settings["minimum_confidence"]=float(settings.get("minimum_confidence",70))
    assets=connector.get_open_assets(min_payout)
    assets=[a for a in assets if market_matches(a["symbol"],settings.get("market_mode","OTC"))]
    logging.info("Ativos com payout >= %.1f%% no filtro %s: %d",min_payout,settings.get("market_mode"),len(assets))
    best=None
    for asset in assets:
        try:
            candles=connector.get_candles(asset["symbol"],seconds,int(settings.get("candles_count",120)))
            result=analyze(candles,settings)
            if not result or result["confidence"] < settings["minimum_confidence"]: continue
            # Estratégia ignora a última vela (em formação); identificar a vela fechada que gerou o sinal.
            signal_ts=candles[-2].get("timestamp") if len(candles)>=2 else None
            candidate={**result,**asset,"timeframe":tf,"expiry_minutes":expiry,"signal_timestamp":signal_ts}
            if best is None or (candidate["confidence"],candidate["payout_percent"])>(best["confidence"],best["payout_percent"]): best=candidate
        except ConnectionError:
            raise
        except Exception as exc: logging.warning("Falha ao analisar %s: %s",asset["symbol"],exc)
    return best

def main():
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
        print("DEMEX AUTOMÁTICO iniciado em PRACTICE/DEMO | M1 | expiração 1 minuto | Harami_GO / CONF_TRIPLA.")
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
                msg=(f"SINAL {signal['symbol']} | {signal['direction']} | {signal['timeframe']} | "
                     f"expiração {signal['expiry_minutes']} min | confiança técnica {signal['confidence']}% | "
                     f"payout {signal['payout_percent']:.1f}%")
                alert(msg,bool(settings.get("sound_alert",True)))
                print("Confirmações: "+", ".join(signal["reasons"]))
                try:
                    summary=trader.execute_and_settle(signal)
                    if summary:
                        print("OPERAÇÃO {result} | Entrada R$ {entry:.2f} | Resultado R$ {pnl:+.2f} | "
                              "Acumulado R$ {session_net:+.2f} | Próxima entrada R$ {next_entry:.2f}".format(**summary))
                        if summary["stopped"]: print("ROBÔ ENCERRADO: "+str(summary["stop_reason"]))
                    else:
                        time.sleep(scan_delay(settings))
                except Exception:
                    logging.exception("Falha na execução/resultado; robô interrompido por segurança.")
                    break
            else:
                print("Nenhum sinal qualificado. Aguardando...")
                time.sleep(scan_delay(settings))
        if trader.stopped:
            print("Sessão encerrada. Resultado líquido: R$ %.2f" % trader.net)
    except KeyboardInterrupt:
        print("\\nRobô encerrado pelo usuário.")
    finally:
        connector.close()

if __name__=="__main__": main()
