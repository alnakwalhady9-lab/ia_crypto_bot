# SMC Bot

SMC-only crypto signal bot for BTC/USDT, ETH/USDT, and SOL/USDT.

Signal sequence:

1. 1H market-structure bias from swing highs and lows.
2. 15m liquidity sweep with a close back inside the swept level.
3. 5m CHoCH confirmed by candle close.
4. 5m Fair Value Gap formed after CHoCH.
5. Alert only when price retests the FVG.

No RSI, EMA, news, harmonic patterns, or automatic trade execution are used.

Environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SYMBOLS` (default: `BTCUSDT,ETHUSDT,SOLUSDT`)
- `SCAN_SECONDS` (default: `60`)
- `STATE_PATH` (optional)

