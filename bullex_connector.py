"""Bullex adapter with market-data reads and guarded PRACTICE-only orders."""
from __future__ import annotations
import logging, os, time, threading
from dataclasses import dataclass
from typing import Any
from bullexapi.stable_api import Bullex
from entry_timing import is_binary_active_open
logger = logging.getLogger(__name__)

@dataclass
class BullexConfig:
    email: str
    password: str
    account_type: str = "PRACTICE"
    @classmethod
    def from_env(cls):
        email=os.getenv("BULLEX_EMAIL","").strip()
        password=os.getenv("BULLEX_PASSWORD","")
        if not email or not password: raise RuntimeError("Configure BULLEX_EMAIL e BULLEX_PASSWORD no .env local.")
        mode=os.getenv("BULLEX_ACCOUNT_TYPE","PRACTICE").upper()
        if mode not in {"PRACTICE","REAL","TOURNAMENT"}: raise ValueError("BULLEX_ACCOUNT_TYPE inválido.")
        return cls(email,password,mode)

class BullexReadOnlyConnector:
    """Leitura de mercado e ordens estritamente bloqueadas fora de PRACTICE."""
    def __init__(self, config):
        self.config=config
        self.client=Bullex(config.email,config.password,active_account_type=config.account_type)
        self.connected=False
        self.account_mode=None
        self.api_lock=threading.RLock()
    def connect(self):
        status,detail=self.client.connect()
        if not status: return {"connected":False,"reason":str(detail or "connection_failed"),"requires_2fa":detail=="2FA"}
        self.connected=bool(self.client.check_connect())
        if self.connected:
            try: self.account_mode=self.client.get_balance_mode()
            except Exception as exc: logger.warning("Falha ao confirmar conta: %s",exc)
        return {"connected":self.connected,"account_type":self.account_mode or self.config.account_type}
    def reconnect_forever(self, stop_check=None):
        """Reconecta continuamente e só retorna após confirmar a conta PRACTICE."""
        delay=2
        while True:
            if stop_check and stop_check():
                raise InterruptedError("Parada solicitada durante a reconexão.")
            try:
                logger.warning("Conexão perdida. Nova tentativa em %s segundos...",delay)
                time.sleep(delay)
                with self.api_lock:
                    try:
                        self.client.logout()
                    except Exception:
                        pass
                    self.client=Bullex(self.config.email,self.config.password,
                                       active_account_type=self.config.account_type)
                    status,detail=self.client.connect()
                    if status and self.client.check_connect():
                        mode=self.client.get_balance_mode()
                        if self.config.account_type!="PRACTICE" or mode!="PRACTICE":
                            raise PermissionError("Reconexão recusada: conta PRACTICE não confirmada.")
                        self.connected=True
                        self.account_mode=mode
                        logger.info("Conexão Bullex restabelecida em PRACTICE.")
                        return True
                    self.connected=False
                    logger.warning("Ainda sem conexão: %s",detail or "sem resposta")
            except PermissionError:
                raise
            except Exception as exc:
                self.connected=False
                logger.warning("Falha na reconexão: %s",exc)
            delay=min(delay*2,30)

    def get_assets(self):
        with self.api_lock:
            self._require_connection()
            return [{"symbol":str(s),"active_id":int(i)} for s,i in self.client.get_all_ACTIVES_OPCODE().items()]
    def get_otc_asset_availability(self):
        """Consulta somente o estado dos ativos OTC da modalidade BINÁRIA, sem enviar ordens."""
        with self.api_lock:
            self._require_connection()
            init_info = self.client.get_all_init_v2(force_refresh=True)
            if not isinstance(init_info, dict):
                raise RuntimeError("A corretora não retornou os dados de disponibilidade dos ativos binários.")
            binary = init_info.get("binary")
            if not isinstance(binary, dict) or not isinstance(binary.get("actives"), dict):
                raise RuntimeError("A resposta da corretora não contém a lista de ativos BINÁRIOS.")
            now_ts = float(self.client.get_server_timestamp())
            result = []
            for active_id, detail in binary["actives"].items():
                if not isinstance(detail, dict):
                    continue
                symbol = str(detail.get("name", active_id)).split(".", 1)[-1]
                if "OTC" not in symbol.upper():
                    continue
                try:
                    numeric_id = int(active_id)
                except (TypeError, ValueError):
                    continue
                result.append({
                    "symbol": symbol,
                    "active_id": numeric_id,
                    "available": is_binary_active_open(detail, now_ts),
                })
            return sorted(result, key=lambda item: item["symbol"])

    def get_candles(self,symbol,timeframe_seconds,count=100):
        with self.api_lock:
            self._require_connection()
            if timeframe_seconds not in (60,300): raise ValueError("Somente M1 e M5.")
            if not 10<=count<=1000: raise ValueError("count deve ficar entre 10 e 1000.")
            if symbol not in self.client.get_all_ACTIVES_OPCODE(): raise ValueError(f"Ativo não encontrado: {symbol}")
            raw=self.client.get_candles(symbol,timeframe_seconds,count,int(self.client.get_server_timestamp()))
            return [{"timestamp":c.get("from",c.get("timestamp")),"open":c.get("open"),"high":c.get("max",c.get("high")),"low":c.get("min",c.get("low")),"close":c.get("close"),"volume":c.get("volume"),"raw":c} for c in (raw or []) if isinstance(c,dict)]
    def get_payouts(self):
        with self.api_lock:
            self._require_connection()
            raw=self.client.get_all_profit()
            result={}
            for symbol,types in (raw.items() if isinstance(raw,dict) else []):
                if not isinstance(types,dict): continue
                result[str(symbol)]={}
                for typ,value in types.items():
                    try:
                        n=float(value); result[str(symbol)][str(typ)]=n*100 if n<=1 else n
                    except (TypeError,ValueError): pass
            return result
    def get_open_assets(self,minimum_payout_percent=85.0,maximum_payout_percent=90.0):
        """Retorna ativos somente pelo payout BINÁRIO, nunca pelo payout de Blitz/Turbo."""
        with self.api_lock:
            minimum=float(minimum_payout_percent)
            maximum=float(maximum_payout_percent)
            if minimum > maximum:
                raise ValueError("Payout mínimo não pode ser maior que o máximo.")
            payouts=self.get_payouts()
            available=[]
            for asset in self.get_assets():
                rates=payouts.get(asset["symbol"],{})
                binary_rate=next(
                    (value for kind,value in rates.items() if str(kind).strip().lower()=="binary"),
                    None
                )
                if binary_rate is None:
                    continue
                binary_rate=round(float(binary_rate),2)
                if minimum <= binary_rate <= maximum:
                    available.append({
                        **asset,
                        "payout_percent":binary_rate,
                        "payout_types":rates,
                        "trade_type":"binary"
                    })
            return available
    def place_practice_order(self,symbol,direction,amount,expiry_minutes):
        with self.api_lock:
            self._require_connection()
            if self.config.account_type!="PRACTICE" or self.client.get_balance_mode()!="PRACTICE":
                raise PermissionError("ORDEM BLOQUEADA: a corretora não confirmou conta PRACTICE/DEMO.")
            if direction not in {"CALL","PUT"}: raise ValueError("Direção inválida.")
            if expiry_minutes not in {1,5}: raise ValueError("Expiração permitida: 1 ou 5 minutos.")
            if float(amount)<=0: raise ValueError("Valor de entrada inválido.")
            if symbol not in self.client.get_all_ACTIVES_OPCODE(): raise ValueError(f"Ativo indisponível: {symbol}")
            ok,order_id=self.client.buy(float(amount),symbol,direction.lower(),int(expiry_minutes))
            if not ok or not order_id: raise RuntimeError(f"Corretora recusou a ordem: {order_id}")
            return int(order_id)
    def wait_practice_result(self,order_id):
        with self.api_lock:
            self._require_connection()
            if self.config.account_type!="PRACTICE" or self.client.get_balance_mode()!="PRACTICE":
                raise PermissionError("Consulta bloqueada: conta não está em PRACTICE.")
            state,pnl=self.client.check_win_v4(int(order_id))
            state=str(state).lower()
            return ("WIN" if state=="win" else "LOSS" if state=="loose" else "TIE",round(float(pnl),2))
    def get_server_timestamp(self):
        with self.api_lock:
            self._require_connection()
            return self.client.get_server_timestamp()
    def _require_connection(self):
        if not self.connected or not self.client.check_connect():
            self.connected=False
            raise ConnectionError("Bullex desconectada; processamento de sinais/ordens interrompido.")
    def close(self):
        with self.api_lock:
            try: self.client.logout()
            finally: self.connected=False
