"""Local smoke test for the read-only Bullex connector.
Run: python main.py
No trading actions are available in this entry point.
"""
import json
import logging
import os
from dotenv import load_dotenv

from bullex_connector import BullexConfig, BullexReadOnlyConnector

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main() -> None:
    load_dotenv()
    connector = BullexReadOnlyConnector(BullexConfig.from_env())
    try:
        result = connector.connect()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("connected"):
            print("Conexão não estabelecida. Verifique credenciais, 2FA e compatibilidade da biblioteca.")
            return
        assets = connector.get_assets()
        print(f"Ativos recebidos: {len(assets)}")
        print(json.dumps(assets[:20], ensure_ascii=False, indent=2))
        symbol = os.getenv("BULLEX_ACTIVE", "EURUSD").strip()
        count = int(os.getenv("BULLEX_CANDLE_COUNT", "100"))
        candles = connector.get_candles(symbol, 60, count)
        print(f"Candles M1 recebidos para {symbol}: {len(candles)}")
        print(json.dumps(candles[-3:], ensure_ascii=False, indent=2))
    finally:
        connector.close()


if __name__ == "__main__":
    main()
