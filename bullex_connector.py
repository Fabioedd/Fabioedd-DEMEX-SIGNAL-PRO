"""Bullex adapter with market-data reads and guarded PRACTICE-only orders."""
from __future__ import annotations
import json
import logging, os, time, threading
from dataclasses import dataclass
from typing import Any
from bullexapi.stable_api import Bullex
from entry_timing import is_binary_active_open
logger = logging.getLogger(__name__)

class OrderRejectedError(RuntimeError):
    """A corretora respondeu explicitamente que não abriu a ordem."""


class OrderConfirmationUnknownError(RuntimeError):
    """O envio terminou sem confirmação/ID; não é seguro reenviar."""



def is_transport_error(exc):
    """Identifica quedas de socket/WebSocket, inclusive Errno 103."""
    import errno
    transport_errnos = {
        errno.ECONNABORTED, errno.ECONNRESET, errno.ENOTCONN,
        errno.EPIPE, errno.ETIMEDOUT, errno.ECONNREFUSED,
        errno.EHOSTUNREACH, errno.ENETUNREACH,
    }
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ConnectionError, TimeoutError, EOFError)):
            return True
        if isinstance(current, OSError) and current.errno in transport_errnos:
            return True
        name = type(current).__name__.lower()
        message = str(current).lower()
        if ("connectionclosed" in name or "websocketconnection" in name
                or "nameresolutionerror" in name or "maxretryerror" in name
                or "connectionerror" in name
                or "software caused connection abort" in message
                or "connection reset" in message or "connection aborted" in message
                or "broken pipe" in message or "websocket is already closed" in message
                or "failed to resolve" in message or "name resolution" in message
                or "temporary failure in name resolution" in message
                or "max retries exceeded" in message or "httpsconnectionpool" in message
                or "getaddrinfo failed" in message):
            return True
        current = current.__cause__ or current.__context__
    return False

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
        """Conecta sem deixar falhas transitórias de DNS/HTTP derrubarem o processo."""
        try:
            status,detail=self.client.connect()
        except Exception as exc:
            self.connected=False
            # A bullexapi pode transformar uma resposta HTTP vazia (por exemplo,
            # quando o DNS falha antes do login) em JSONDecodeError. Isso é falha
            # de transporte/handshake, não motivo para encerrar o DEMEX.
            if is_transport_error(exc) or isinstance(exc, json.JSONDecodeError):
                reason="{}: {}".format(type(exc).__name__, exc)
                logger.warning(
                    "Conexão inicial BullX indisponível (%s). O DEMEX poderá tentar novamente.",
                    reason
                )
                return {"connected":False,"reason":reason,"requires_2fa":False}
            raise
        if not status: return {"connected":False,"reason":str(detail or "connection_failed"),"requires_2fa":detail=="2FA"}
        self.connected=bool(self.client.check_connect())
        if self.connected:
            try: self.account_mode=self.client.get_balance_mode()
            except Exception as exc: logger.warning("Falha ao confirmar conta: %s",exc)
        return {"connected":self.connected,"account_type":self.account_mode or self.config.account_type}
    def _wait_for_retry(self, delay, stop_check=None):
        """Aguarda a próxima tentativa em pequenos intervalos, respeitando /stop."""
        deadline = time.monotonic() + max(0.0, float(delay))
        while True:
            if stop_check and stop_check():
                raise InterruptedError("Parada solicitada durante a reconexão.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.25, remaining))

    def reconnect_forever(self, stop_check=None):
        """Reconecta continuamente e só retorna após confirmar a conta PRACTICE."""
        delay=2
        while True:
            if stop_check and stop_check():
                raise InterruptedError("Parada solicitada durante a reconexão.")
            try:
                logger.warning("Conexão perdida. Nova tentativa em %s segundos...",delay)
                self._wait_for_retry(delay, stop_check)
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
            # O mapa de ativos da própria API é a fonte mais confiável para o símbolo
            # usado em get_candles/buy. O campo "name" pode conter sufixos de tipo.
            id_to_symbol = {}
            for known_symbol, known_id in self.client.get_all_ACTIVES_OPCODE().items():
                try:
                    id_to_symbol[int(known_id)] = str(known_symbol)
                except (TypeError, ValueError):
                    continue

            result = []
            for active_id, detail in binary["actives"].items():
                if not isinstance(detail, dict):
                    continue
                try:
                    numeric_id = int(active_id)
                except (TypeError, ValueError):
                    continue

                symbol = id_to_symbol.get(numeric_id)
                if not symbol:
                    raw_name = str(detail.get("name", ""))
                    # Aceita nomes como "binary.EURUSD-OTC" e "EURUSD-OTC.op"
                    # sem cortar o símbolo no ponto errado.
                    parts = [part for part in raw_name.split(".") if part]
                    symbol = next(
                        (part for part in parts if "OTC" in part.upper()),
                        raw_name,
                    )
                if "OTC" not in symbol.upper():
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
            if ok and order_id:
                return int(order_id)
            # A biblioteca também retorna (False, None) quando esgota seu timeout
            # interno. Não sabemos se a corretora recebeu a ordem; nunca reenviar,
            # pois isso poderia duplicar uma operação.
            if order_id is None:
                raise OrderConfirmationUnknownError(
                    "A BullX não confirmou a ordem nem devolveu ID (timeout/resposta ausente). "
                    "Estado desconhecido; reenvio automático bloqueado por segurança."
                )
            raise OrderRejectedError(f"A BullX recusou explicitamente a ordem: {order_id}")
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
        """Encerra localmente sem derrubar o robô se a sessão remota já caiu."""
        with self.api_lock:
            try:
                if self.connected:
                    self.client.logout()
            except Exception as exc:
                # Logout é limpeza best-effort: uma queda da rede durante o
                # encerramento não deve mascarar o motivo real da parada.
                logger.warning("Falha ao encerrar sessão remota da BullX: %s", exc)
            finally:
                self.connected = False
