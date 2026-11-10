"""DEMEX read-only signal scanner. Never places trades."""
import json
import logging
import os
import time
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from bullex_connector import BullexConfig, BullexReadOnlyConnector
from signal_engine import analyze

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def load_settings():
    with open("settings.json", encoding="utf-8") as f:
        return json.load(f)

def alert(message, enabled=True):
    print("\\a" + message, flush=True)
    if enabled:
        # Optional Termux:API speech; scanner still works if unavailable.
        try:
            subprocess.Popen(["termux-tts-speak", message])
        except (FileNotFoundError, OSError):
            pass

def market_matches(symbol, mode):
    is_otc = "OTC" in symbol.upper()
    return is_otc if mode.upper() == "OTC" else not is_otc

def scan_once(connector, settings):
    tf = settings.get("timeframe", "M1").upper()
    seconds = 60 if tf == "M1" else 300 if tf == "M5" else None
    if seconds is None:
        raise ValueError("timeframe deve ser M1 ou M5")
    expiry = int(settings.get("expiry_minutes", 1 if tf == "M1" else 5))
    minimum_payout = float(settings.get("minimum_payout_percent", 80))
    minimum_confidence = float(settings.get("minimum_confidence", 70))
    settings["minimum_confidence"] = minimum_confidence
    assets = connector.get_open_assets(minimum_payout)
    assets = [a for a in assets if market_matches(a["symbol"], settings.get("market_mode", "OTC"))]
    logging.info("Ativos com payout >= %.1f%% no filtro %s: %d", minimum_payout, settings.get("market_mode"), len(assets))
    best = None
    for asset in assets:
        try:
            candles = connector.get_candles(asset["symbol"], seconds, int(settings.get("candles_count", 120)))
            result = analyze(candles, settings)
            if not result or result["confidence"] < minimum_confidence:
                continue
            candidate = {**result, **asset, "timeframe": tf, "expiry_minutes": expiry}
            if best is None or (candidate["confidence"], candidate["payout_percent"]) > (best["confidence"], best["payout_percent"]):
                best = candidate
        except Exception as exc:
            logging.warning("Falha ao analisar %s: %s", asset["symbol"], exc)
    return best

def main():
    load_dotenv()
    settings = load_settings()
    connector = BullexReadOnlyConnector(BullexConfig.from_env())
    try:
        status = connector.connect()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        if not status.get("connected"):
            print("Conexão não estabelecida. Verifique credenciais, 2FA e compatibilidade do pacote.")
            return
        print("DEMEX SIGNAL SCANNER iniciado. Somente leitura; nenhuma ordem será enviada.")
        while True:
            signal = scan_once(connector, settings)
            if signal:
                message = (f"SINAL {signal['symbol']} | {signal['direction']} | {signal['timeframe']} | "
                           f"expiração {signal['expiry_minutes']} min | confiança técnica {signal['confidence']}% | "
                           f"payout {signal['payout_percent']:.1f}%")
                alert(message, bool(settings.get("sound_alert", True)))
                print("Confirmações: " + ", ".join(signal["reasons"]))
                print("Aguardando o ciclo de expiração antes de procurar outro sinal.")
                time.sleep(max(1, signal["expiry_minutes"] * 60))
            else:
                print("Nenhum sinal qualificado. Aguardando...")
                time.sleep(max(3, int(settings.get("scan_interval_seconds", 8))))
    except KeyboardInterrupt:
        print("\\nScanner encerrado pelo usuário.")
    finally:
        connector.close()

if __name__ == "__main__":
    main()
