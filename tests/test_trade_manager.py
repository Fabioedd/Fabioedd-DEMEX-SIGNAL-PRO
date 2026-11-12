import unittest
from decimal import Decimal
from trade_manager import DemoTrader

class FakeClient:
    def get_balance_mode(self): return "PRACTICE"
class FakeConnector:
    class Config: account_type="PRACTICE"
    config=Config()
    client=FakeClient()
    def __init__(self, results): self.results=list(results); self.orders=[]; self.reconnects=0; self.connected=True
    def place_practice_order(self,symbol,direction,amount,expiry):
        self.orders.append((symbol,direction,amount,expiry))
        return len(self.orders)
    def wait_practice_result(self,order_id):
        item=self.results.pop(0)
        if isinstance(item, BaseException): raise item
        return item
    def reconnect_forever(self,stop_check=None):
        if stop_check and stop_check(): raise InterruptedError("stop")
        self.reconnects += 1
        self.connected=True
        return True

class TradeManagerTests(unittest.TestCase):
    def settings(self):
        return {"expiry_minutes":1,"trading":{"initial_entry_brl":5,"stop_loss_brl":15,"take_profit_brl":30}}
    def signal(self,n=1):
        return {"symbol":"EURUSD-OTC","direction":"CALL","signal_timestamp":n}
    def test_soros_one_then_reset(self):
        c=FakeConnector([("WIN",4.25),("WIN",7.86)])
        t=DemoTrader(c,self.settings())
        a=t.execute_and_settle(self.signal(1))
        self.assertEqual(a["entry"],5.0)
        self.assertEqual(a["next_entry"],9.25)
        b=t.execute_and_settle(self.signal(2))
        self.assertEqual(b["entry"],9.25)
        self.assertEqual(b["next_entry"],5.0)
    def test_loss_resets_entry(self):
        c=FakeConnector([("LOSS",-5.0)])
        t=DemoTrader(c,self.settings())
        r=t.execute_and_settle(self.signal())
        self.assertEqual(r["next_entry"],5.0)
        self.assertEqual(r["session_net"],-5.0)
    def test_stop_loss_stops_session(self):
        c=FakeConnector([("LOSS",-5.0),("LOSS",-5.0),("LOSS",-5.0)])
        t=DemoTrader(c,self.settings())
        t.execute_and_settle(self.signal(1))
        t.execute_and_settle(self.signal(2))
        r=t.execute_and_settle(self.signal(3))
        self.assertTrue(r["stopped"])
        self.assertEqual(r["session_net"],-15.0)
        self.assertIsNone(t.execute_and_settle(self.signal(4)))
    def test_errno_103_reconnects_and_checks_same_order_without_duplicate(self):
        c=FakeConnector([ConnectionAbortedError(103, "Software caused connection abort"), ("WIN",4.25)])
        t=DemoTrader(c,self.settings())
        r=t.execute_and_settle(self.signal())
        self.assertEqual(r["result"],"WIN")
        self.assertEqual(c.reconnects,1)
        self.assertEqual(len(c.orders),1)
        self.assertEqual(t.total_entries,1)

    def test_take_profit_stops_session(self):
        c=FakeConnector([("WIN",30.0)])
        t=DemoTrader(c,self.settings())
        r=t.execute_and_settle(self.signal())
        self.assertTrue(r["stopped"])
        self.assertEqual(r["session_net"],30.0)

if __name__=="__main__": unittest.main()
