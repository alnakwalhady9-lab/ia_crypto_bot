import os
import time
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GOLD_API_URL = os.getenv("GOLD_API_URL")
GOLD_API_KEY = os.getenv("GOLD_API_KEY")

# Phase 1: alert-only XAU/USD scalper. No broker orders are placed.
# Data provider is intentionally configurable because reliable intraday XAU/USD
# candles require a market-data source that supports gold.


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10
        )
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"Telegram error: {e}")


def ema(values, period):
    k = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * k + result * (1 - k)
    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in changes[-period:]]
    losses = [max(-x, 0) for x in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def atr(candles, period=14):
    if len(candles) <= period:
        return None
    tr = []
    for i in range(1, len(candles)):
        high, low = candles[i]["high"], candles[i]["low"]
        prev_close = candles[i-1]["close"]
        tr.append(max(high-low, abs(high-prev_close), abs(low-prev_close)))
    return sum(tr[-period:]) / period


def normalize_candles(payload):
    # Expected normalized response: [{time, open, high, low, close, volume?}, ...]
    rows = payload.get("candles", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None
    result = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        try:
            result.append({
                "time": x.get("time", x.get("timestamp")),
                "open": float(x["open"]), "high": float(x["high"]),
                "low": float(x["low"]), "close": float(x["close"]),
                "volume": float(x.get("volume", 0) or 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return result


def get_candles(interval):
    if not GOLD_API_URL:
        print("Gold bot waiting for GOLD_API_URL market-data provider")
        return None
    headers = {"Accept": "application/json", "User-Agent": "gold-scalper/1.0"}
    if GOLD_API_KEY:
        headers["Authorization"] = f"Bearer {GOLD_API_KEY}"
    try:
        r = requests.get(GOLD_API_URL, params={"symbol": "XAUUSD", "interval": interval, "limit": 200}, headers=headers, timeout=15)
        r.raise_for_status()
        return normalize_candles(r.json())
    except (requests.RequestException, ValueError) as e:
        print(f"Gold data error ({interval}): {e}")
        return None


def snapshot(candles):
    if not candles or len(candles) < 55:
        return None
    closed = candles[:-1]
    closes = [x["close"] for x in closed]
    return {
        "price": closes[-1], "ema9": ema(closes[-40:], 9),
        "ema20": ema(closes[-50:], 20), "ema50": ema(closes[-55:], 50),
        "rsi": rsi(closes), "atr": atr(closed), "candles": closed
    }


def trend(s):
    if s["price"] > s["ema9"] > s["ema20"] > s["ema50"]:
        return "BULLISH"
    if s["price"] < s["ema9"] < s["ema20"] < s["ema50"]:
        return "BEARISH"
    return "MIXED"


def analyze():
    # Scalping trigger on 5m, confirmation on 15m and 1h.
    s5, s15, s1h = snapshot(get_candles("5m")), snapshot(get_candles("15m")), snapshot(get_candles("1h"))
    if not all((s5, s15, s1h)):
        return None
    t5, t15, t1h = trend(s5), trend(s15), trend(s1h)
    price, r = s5["price"], s5["rsi"]
    recent = s5["candles"][-20:]
    support = min(x["low"] for x in recent)
    resistance = max(x["high"] for x in recent)
    score = 0
    side = "WAIT"
    reasons = []

    if t5 == "BULLISH" and r is not None and 52 <= r <= 72:
        side, score = "BUY", 50
        reasons.append("5m bullish momentum")
        if t15 == "BULLISH": score += 20; reasons.append("15m confirms")
        if t1h == "BULLISH": score += 15; reasons.append("1h confirms")
        if t15 == "BEARISH": score -= 20
    elif t5 == "BEARISH" and r is not None and 28 <= r <= 48:
        side, score = "SELL", 50
        reasons.append("5m bearish momentum")
        if t15 == "BEARISH": score += 20; reasons.append("15m confirms")
        if t1h == "BEARISH": score += 15; reasons.append("1h confirms")
        if t15 == "BULLISH": score -= 20

    score = max(0, min(100, score))
    if score < 70:
        side = "WAIT"
    a = s5["atr"] or price * 0.001
    sl = price - 1.2*a if side == "BUY" else price + 1.2*a if side == "SELL" else None
    tp = price + 1.8*a if side == "BUY" else price - 1.8*a if side == "SELL" else None
    return {"side": side, "price": price, "rsi": r, "atr": a, "support": support,
            "resistance": resistance, "score": score, "t5": t5, "t15": t15,
            "t1h": t1h, "sl": sl, "tp": tp, "reasons": reasons}


last_signal = None
last_report = 0
while True:
    result = analyze()
    if result:
        print(f'XAUUSD {result["price"]:.2f} | {result["side"]} | RSI {result["rsi"]:.1f} | 5m/15m/1h {result["t5"]}/{result["t15"]}/{result["t1h"]} | ATR {result["atr"]:.2f} | Confidence {result["score"]}%')
        now = time.time()
        # Full status every 15 minutes, plus immediate new BUY/SELL alerts.
        periodic = now - last_report >= 900
        immediate = result["side"] in ("BUY", "SELL") and result["side"] != last_signal
        if periodic or immediate:
            risk = "WAIT - no entry" if result["side"] == "WAIT" else f'SL: {result["sl"]:.2f} | TP: {result["tp"]:.2f}'
            send_telegram(
                f'GOLD SCALPER XAU/USD\nSignal: {result["side"]}\nPrice: {result["price"]:.2f}\nConfidence: {result["score"]}%\n'
                f'RSI: {result["rsi"]:.1f}\n5m/15m/1h: {result["t5"]}/{result["t15"]}/{result["t1h"]}\n'
                f'ATR: {result["atr"]:.2f}\nSupport: {result["support"]:.2f}\nResistance: {result["resistance"]:.2f}\n{risk}\n'
                f'Reason: {"; ".join(result["reasons"]) or "No confirmed scalp setup"}\nAlert only - no trade executed.'
            )
            if periodic: last_report = now
        last_signal = result["side"]
    time.sleep(30)
