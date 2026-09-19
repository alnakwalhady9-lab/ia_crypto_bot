# SMC Bot

SMC-only crypto signal bot for BTC/USDT, ETH/USDT, and SOL/USDT.

Signal sequence:

1. 1H market-structure bias from swing highs and lows.
2. 15m liquidity sweep with a close back inside the swept level.
3. 5m CHoCH confirmed by candle close.
4. 5m Fair Value Gap formed after CHoCH.
5. Alert only when price retests the FVG.

No RSI, EMA, news, harmonic patterns, or automatic trade execution are used.

The bot simulates trades in an isolated paper portfolio. Defaults are a $5,000
starting balance, 1% risk per trade, 3% maximum concurrent risk, and a 2x
notional cap. TP1 and TP2 are notifications; a trade closes only at TP3 or SL.
It posts a portfolio report every two hours.

Environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SYMBOLS` (default: `BTCUSDT,ETHUSDT,SOLUSDT`)
- `SCAN_SECONDS` (default: `60`)
- `REPORT_SECONDS` (default: `7200`)
- `INITIAL_BALANCE` (default: `5000`)
- `RISK_PER_TRADE` (default: `0.01`)
- `MAX_TOTAL_RISK` (default: `0.03`)
- `MAX_NOTIONAL_MULTIPLIER` (default: `2`)
- `STATE_PATH` (optional)
