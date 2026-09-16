import os
import time
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}

    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        print("Telegram message sent successfully")
    except requests.exceptions.RequestException as e:
        print(f"Telegram error: {e}")


def get_binance_klines(interval="15m", limit=100):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Binance API error: {e}")
        return None


def ema(values, period):
    multiplier = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = (value * multiplier) + (result * (1 - multiplier))
    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze_market():
    klines = get_binance_klines()
    if not klines or len(klines) < 50:
        return None

    # Ignore the currently forming candle; analyze closed 15-minute candles only.
    closed = klines[:-1]
    closes = [float(k[4]) for k in closed]
    volumes = [float(k[5]) for k in closed]

    price = closes[-1]
    ema20 = ema(closes[-50:], 20)
    ema50 = ema(closes[-50:], 50)
    rsi14 = rsi(closes, 14)
    avg_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / avg_volume if avg_volume else 0

    signal = "WAIT"
    reasons = []

    if price > ema20 > ema50 and rsi14 is not None and 52 <= rsi14 <= 70 and volume_ratio >= 1.05:
        signal = "LONG"
        reasons.append("Price and EMA20 are above EMA50")
        reasons.append("RSI confirms bullish momentum")
        reasons.append("Volume is above its recent average")
    elif price < ema20 < ema50 and rsi14 is not None and 30 <= rsi14 <= 48 and volume_ratio >= 1.05:
        signal = "SHORT"
        reasons.append("Price and EMA20 are below EMA50")
        reasons.append("RSI confirms bearish momentum")
        reasons.append("Volume is above its recent average")
    else:
        reasons.append("No high-confidence technical setup yet")

    # Informational levels only; no orders are placed.
    risk_distance = price * 0.01
    if signal == "LONG":
        stop_loss = price - risk_distance
        take_profit = price + (risk_distance * 2)
    elif signal == "SHORT":
        stop_loss = price + risk_distance
        take_profit = price - (risk_distance * 2)
    else:
        stop_loss = None
        take_profit = None

    return {
        "signal": signal,
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "volume_ratio": volume_ratio,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "reasons": reasons,
    }


last_signal = None

while True:
    analysis = analyze_market()

    if analysis:
        signal = analysis["signal"]
        print(
            f'BTCUSDT: {analysis["price"]:.2f} | '
            f'Signal: {signal} | RSI: {analysis["rsi"]:.1f}'
        )

        # Send only when a new actionable signal appears, avoiding Telegram spam.
        if signal in ("LONG", "SHORT") and signal != last_signal:
            message = (
                f'BTC/USDT SIGNAL: {signal}\n'
                f'Entry reference: {analysis["price"]:.2f}\n'
                f'Stop Loss: {analysis["stop_loss"]:.2f}\n'
                f'Take Profit: {analysis["take_profit"]:.2f}\n'
                f'RSI(14): {analysis["rsi"]:.1f}\n'
                f'Volume ratio: {analysis["volume_ratio"]:.2f}x\n'
                f'Why: {"; ".join(analysis["reasons"])}\n\n'
                'Analysis alert only - no trade was executed.'
            )
            send_telegram_message(message)

        last_signal = signal

    time.sleep(60)
