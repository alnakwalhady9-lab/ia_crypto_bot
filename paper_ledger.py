"""Durable, paper-only trade state and append-only events (SQLite on /data)."""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


class Ledger:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at REAL, kind TEXT, symbol TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS signals(symbol TEXT PRIMARY KEY, side TEXT, bar INTEGER);
        ''')

    def positions(self):
        return {s: json.loads(p) for s, p in self.db.execute('SELECT symbol,payload FROM positions')}

    def _event(self, kind, symbol, payload):
        self.db.execute('INSERT INTO events(at,kind,symbol,payload) VALUES(?,?,?,?)',
                        (time.time(), kind, symbol, json.dumps(payload)))

    def save(self, symbol, position, opening=False):
        with self.db:
            if opening:
                self.db.execute('INSERT INTO positions VALUES(?,?)', (symbol, json.dumps(position)))
                self._event('OPEN', symbol, position)
            else:
                self.db.execute('UPDATE positions SET payload=? WHERE symbol=?', (json.dumps(position), symbol))

    def close(self, symbol, position, result, exit_price, bar):
        move = (exit_price-position['entry']) * (1 if position['side']=='LONG' else -1)
        quantity = position['lot_size'] * position['contract']
        net = (move-position['spread']) * quantity
        event = dict(position, result=result, exit=exit_price, closed_bar=bar,
                     closed_at=time.time(), delta=move, net_pnl=net,
                     net_r=net/position['planned_risk'])
        with self.db:
            self._event('CLOSE', symbol, event)
            self.db.execute('DELETE FROM positions WHERE symbol=?', (symbol,))
        return event

    def observe_signal(self, symbol, side, bar):
        old = self.db.execute('SELECT side,bar FROM signals WHERE symbol=?', (symbol,)).fetchone()
        fresh = old is None or (bar >= old[1] and side != old[0])
        if old is None or bar >= old[1]:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO signals VALUES(?,?,?)', (symbol, side, bar))
        return fresh

    def note(self, kind, symbol, payload):
        with self.db:
            self._event(kind, symbol, payload)


def new_position(x):
    return dict(id=str(uuid.uuid4()), side=x['side'], entry=x['p'], sl=x['sl'], tp=x['tp'],
                opened_at=time.time(), opened_bar=int(x['c'][-1][0]),
                last_bar=int(x['c'][-1][0]), lot_size=x['lot_size'],
                planned_risk=x['dollar_risk'], spread=x['spread'], contract=x['contract'],
                code_version=os.getenv('RAILWAY_GIT_COMMIT_SHA','local'),
                reason=x['why'], buy_score=x['bp'], sell_score=x['sp'], phase='btc-eth-paper-v1')
