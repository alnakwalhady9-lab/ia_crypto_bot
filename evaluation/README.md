# BTC history and BTC/ETH paper phase — 2026-10-19

User instruction: disable EUR/USD and USD/JPY; preserve BTC records; add Ethereum.

## Preserved history

`legacy_issue_4_2026-10-19.json` is an unmodified snapshot of all 33 issue comments, including every BTC entry/exit table, costs, duplicates and corrections. Source: https://github.com/alnakwalhady9-lab/ia_crypto_bot/issues/4

BTC historical closed sample: 23 trades, 12 TP, 11 SL, +13 gross R, 3R closed-trade drawdown. These results remain historical and must not be merged into the new phase without labeling code version and execution assumptions.

Last explicitly reported BTC balance: $5,195.20 after 9 closed BTC trades. Applying the recorded fixed $50 risk budget, $30/BTC spread, 1 BTC per lot, and rounding lots down to 0.01 to the next 14 trades reconstructs +$249.2871, giving an estimated historical balance of $5,444.49. Those 14 volumes are reconstructed, not observed fills. No commissions, swap or slippage are included. The new phase does not treat this estimate as a verified cash balance.

The last historical BTC LONG (entry 86174.18) and JPY LONG had no closing record in issue #4. They remain unresolved historical positions. They are not silently closed or restored as new trades from stale environment variables. Railway's historical deployment ac18a0f1 was REMOVED on October 10; no live position state was available during this change.

## New phase

Only BTC/USD and ETH/USD are fetched and permitted. EUR/USD and USD/JPY have no active analysis, restoration, opening or alert path. PAPER_MODE is enforced in code.

ETH uses Coinbase ETH-USD candles and the same technical 15m/1h/4h entry scoring as BTC, target 2x stop distance. Its evaluation starts at zero trades and is recorded separately. Existing BTC risk variables are preserved. ETH uses 1 ETH per paper lot, 0.01 quantity step, and a **simulation-only $2/ETH spread assumption** (`ETH_SPREAD_USD`), not a broker quote. Both symbols share the existing BTC account risk budget; adding ETH does not create another $5,000 account or double simultaneous permitted risk.

Existing BTC scoring is preserved. News/Reddit do not score entries and their unused network calls are removed. Percentages are heuristic bias scores, not calibrated win probabilities.

Open positions, entry versions, sizes, costs, signal deduplication and append-only events are persisted in SQLite at `/data/crypto-paper.sqlite3` on a Railway volume. All unseen closed candles are replayed in time order; a missing candle quarantines the position rather than inventing an outcome. Same-candle TP and SL is marked SL_AMBIGUOUS and assigned the stop conservatively. Signals with a stale last closed 15m candle are blocked.

The simulation assumes entry at the completed signal candle close and exits at the specified level; it does not model execution latency, commissions, gaps beyond the stop or slippage. This implementation change starts a separately labeled phase `btc-eth-paper-v1`.

## Checks

Run `python -m unittest discover -s . -p 'test_*.py' -v` from repository root. Tests cover persistence across restart, historical-bar exclusion, unseen-bar replay, gap quarantine, ambiguous exits, combined risk limits, disabled forex, ETH feed selection and persistent signal deduplication.
