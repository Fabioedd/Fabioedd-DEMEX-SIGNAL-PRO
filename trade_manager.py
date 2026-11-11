"""DEMO order runner with R$5 base, Soros 1, stop and take."""
from decimal import Decimal, ROUND_HALF_UP
import logging
log=logging.getLogger(__name__)
def money(v): return Decimal(str(v)).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)

class DemoTrader:
    def __init__(self,connector,settings):
        self.connector=connector
        self.expiry=int(settings.get("expiry_minutes",1))
        cfg=settings["trading"]
        self.base=money(cfg["initial_entry_brl"])
        self.stop=money(cfg["stop_loss_brl"])
        self.take=money(cfg["take_profit_brl"])
        self.net=Decimal("0.00")
        self.total_entries=0
        self.wins=0
        self.losses=0
        self.ties=0
        self.next_entry=self.base
        self.soros_step=0
        self.last_signal_key=None
        self.busy=False
        self.stopped=False
    def execute_and_settle(self,signal):
        if self.busy or self.stopped: return None
        if self.connector.config.account_type!="PRACTICE" or self.connector.client.get_balance_mode()!="PRACTICE":
            raise PermissionError("Robô bloqueado: conta PRACTICE/DEMO não confirmada.")
        key="{}|{}|{}".format(signal["symbol"],signal["direction"],signal.get("signal_timestamp"))
        if key==self.last_signal_key:
            log.warning("Sinal duplicado ignorado: %s",key); return None
        self.last_signal_key=key
        self.busy=True
        try:
            amount=min(self.next_entry,money(self.stop+self.net))
            if amount<=0:
                self.stopped=True; return None
            order_id=self.connector.place_practice_order(signal["symbol"],signal["direction"],float(amount),self.expiry)
            log.info("ORDEM DEMO | %s | %s | R$ %.2f | ID %s",signal["symbol"],signal["direction"],amount,order_id)
            # A ordem já foi enviada: em caso de queda, reconectar e consultar
            # o MESMO order_id. Nunca enviar uma segunda ordem para substituir esta.
            while True:
                try:
                    result,pnl_raw=self.connector.wait_practice_result(order_id)
                    break
                except Exception:
                    try:
                        connected=(self.connector.connected and self.connector.client.check_connect())
                    except Exception:
                        connected=False
                    if connected:
                        raise
                    log.warning("Conexão caiu aguardando resultado da ordem %s; reconectando para consultar a mesma ordem.",order_id)
                    self.connector.reconnect_forever()
            pnl=money(pnl_raw); self.net=money(self.net+pnl)
            self.total_entries += 1
            if result == "WIN": self.wins += 1
            elif result == "LOSS": self.losses += 1
            else: self.ties += 1
            decisive = self.wins + self.losses
            win_rate = (100.0 * self.wins / decisive) if decisive else 0.0
            # Soros nível 1: apenas uma recuperação após WIN; depois reinicia.
            if result=="WIN" and self.soros_step==0:
                self.next_entry=money(self.base+pnl); self.soros_step=1
            else:
                self.next_entry=self.base; self.soros_step=0
            if self.net<=-self.stop:
                self.stopped=True; reason="STOP LOSS atingido"
            elif self.net>=self.take:
                self.stopped=True; reason="TAKE PROFIT atingido"
            else: reason=None
            # Cap next stake so a single loss cannot exceed the remaining stop budget.
            if not self.stopped:
                self.next_entry=min(self.next_entry,money(self.stop+self.net))
            summary={"order_id":order_id,"symbol":signal["symbol"],"direction":signal["direction"],
                     "entry":float(amount),"expiry_minutes":self.expiry,"result":result,
                     "pnl":float(pnl),"session_net":float(self.net),"next_entry":float(self.next_entry),
                     "stopped":self.stopped,"stop_reason":reason,"total_entries":self.total_entries,
                     "wins":self.wins,"losses":self.losses,"ties":self.ties,"win_rate":round(win_rate,2)}
            log.info("RESULTADO %s | P&L R$ %.2f | acumulado R$ %.2f | próxima entrada R$ %.2f",
                     result,pnl,self.net,self.next_entry)
            if self.stopped: log.warning("ROBÔ PARADO: %s",reason)
            return summary
        finally:
            self.busy=False
