import importlib
import os
import tempfile
import unittest
from unittest.mock import patch

class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        os.environ['PAPER_DB_PATH']=self.tmp.name+'/paper.sqlite3'
        import main
        self.m=importlib.reload(main)
        self.m.send=lambda message:None
        self.x=dict(side='LONG',p=100,sl=90,tp=120,c=[[900,99,101,100,100,1]],
                    lot_size=1,dollar_risk=12,spread=2,contract=1,why=[],bp=80,sp=20)
    def tearDown(self):
        self.m.LEDGER.db.close()
        self.tmp.cleanup()
    def test_restart_retains_open_and_close_without_resurrecting(self):
        self.assertTrue(self.m.paper_open('BTC/USD',self.x,'test'))
        from paper_ledger import Ledger
        reopened=Ledger(os.environ['PAPER_DB_PATH'])
        self.assertEqual(len(reopened.positions()),1)
        reopened.db.close()
        self.m.paper_track('BTC/USD',dict(self.x,c=self.x['c']+[[1800,99,121,100,120,1]]))
        self.assertEqual(self.m.LEDGER.positions(),{})
        row=self.m.LEDGER.db.execute("SELECT payload FROM events WHERE kind='CLOSE'").fetchone()
        import json
        self.assertEqual(json.loads(row[0])['net_pnl'],18)
    def test_replay_missed_stop_before_later_target(self):
        self.m.paper_open('BTC/USD',self.x,'test')
        self.m.paper_track('BTC/USD',dict(self.x,c=[[1800,89,105,100,95,1],[2700,95,121,95,120,1]]))
        self.assertEqual(self.m.LEDGER.positions(),{})
        import json
        result=json.loads(self.m.LEDGER.db.execute("SELECT payload FROM events WHERE kind='CLOSE'").fetchone()[0])
        self.assertEqual(result['result'],'SL')
    def test_gap_does_not_invent_result(self):
        self.m.paper_open('BTC/USD',self.x,'test')
        self.m.paper_track('BTC/USD',dict(self.x,c=[[2700,89,121,100,100,1]]))
        self.assertTrue(self.m.paper['BTC/USD']['data_gap'])
        self.assertEqual(self.m.LEDGER.db.execute("SELECT count(*) FROM events WHERE kind='CLOSE'").fetchone()[0],0)
    def test_old_bar_cannot_close_trade_and_ambiguous_is_stop(self):
        self.m.paper_open('BTC/USD',self.x,'test')
        self.m.paper_track('BTC/USD',dict(self.x,c=[[900,1,500,100,100,1]]))
        self.assertIn('BTC/USD',self.m.paper)
        self.m.paper_track('BTC/USD',dict(self.x,c=[[1800,89,121,100,100,1]]))
        import json
        result=json.loads(self.m.LEDGER.db.execute("SELECT payload FROM events WHERE kind='CLOSE'").fetchone()[0])
        self.assertEqual(result['result'],'SL_AMBIGUOUS')
    def test_disabled_symbols_and_combined_risk(self):
        self.assertFalse(self.m.paper_open('EUR/USD',self.x,'test'))
        self.assertFalse(self.m.paper_open('USD/JPY',self.x,'test'))
        x=dict(self.x,dollar_risk=49)
        self.assertTrue(self.m.paper_open('BTC/USD',x,'test'))
        self.assertFalse(self.m.paper_open('ETH/USD',x,'test'))
    def test_eth_feed_and_sizing_are_independent(self):
        import time
        start=int(time.time()//900)*900
        def fake(g,n,product):
            return [[start-(n-i-1)*g,1900+i,1902+i,1901+i,1901+i,10] for i in range(n)]
        with patch.object(self.m,'candles',side_effect=fake) as feed, patch.object(self.m,'sentiment',return_value='NEUTRAL'), patch.object(self.m,'reddit',return_value='NEUTRAL'):
            x=self.m.analyze('ETH-USD')
            self.assertIsNotNone(x)
            self.assertEqual(x['spread'],2)
            self.assertTrue(all(call.args[2]=='ETH-USD' for call in feed.call_args_list))
    def test_signal_dedup_survives_restart(self):
        from paper_ledger import Ledger
        self.assertTrue(self.m.LEDGER.observe_signal('BTC/USD','LONG',900))
        reopened=Ledger(os.environ['PAPER_DB_PATH'])
        self.assertFalse(reopened.observe_signal('BTC/USD','LONG',1800))
        self.assertTrue(reopened.observe_signal('BTC/USD','SHORT',1800))
        reopened.db.close()

if __name__=='__main__':unittest.main()
