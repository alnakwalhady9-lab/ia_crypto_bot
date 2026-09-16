import os
import time
import re
import xml.etree.ElementTree as ET
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

NEWS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]

POSITIVE_NEWS_WORDS = {
    "approval", "approved", "adoption", "bullish", "surge", "rally", "record",
    "inflows", "buying", "growth", "breakout", "launch", "partnership", "easing",
}
NEGATIVE_NEWS_WORDS = {
    "hack", "hacked", "exploit", "ban", "lawsuit", "crackdown", "bearish", "plunge",
    "selloff", "outflows", "liquidation", "fraud", "breach", "rejection", "tightening",
}
BTC_NEWS_WORDS = {
    "bitcoin", "btc", "crypto", "cryptocurrency", "etf", "sec", "fed", "federal reserve",
    "inflation", "interest rate", "rates", "cpi", "tariff", "regulation",
}


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


def clean_text(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def get_news_sentiment():
    headlines = []

    for feed_url in NEWS_FEEDS:
        try:
            response = requests.get(
                feed_url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 ia-crypto-bot/1.0"},
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)

            for item in root.findall(".//item")[:15]:
                title = clean_text(item.findtext("title"))
                description = clean_text(item.findtext("description"))
                text = f"{title} {description}".lower()
                if any(word in text for word in BTC_NEWS_WORDS):
                    headlines.append(title)
        except (requests.exceptions.RequestException, ET.ParseError) as e:
            print(f"News feed error ({feed_url}): {e}")

    # Remove duplicate headlines while preserving order.
    headlines = list(dict.fromkeys(headlines))[:20]
    if not headlines:
        return {"label": "NEUTRAL", "score": 0, "headlines": []}

    score = 0
    for headline in headlines:
        words = headline.lower()
        score += sum(1 for word in POSITIVE_NEWS_WORDS if word in words)
        score -= sum(1 for word in NEGATIVE_NEWS_WORDS if word in words)

    if score >= 2:
        label = "POSITIVE"
    elif score <= -2:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"

    return {"label": label, "score": score, "headlines": headlines[:3]}


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

    technical_signal = "WAIT"
    reasons = []

    if price > ema20 > ema50 and rsi14 is not None and 52 <= rsi14 <= 70 and volume_ratio >= 1.05:
        technical_signal = "LONG"
        reasons.extend([
            "Price and EMA20 are above EMA50",
            "RSI confirms bullish momentum",
            "Volume is above its recent average",
        ])
    elif price < ema20 < ema50 and rsi14 is not None and 30 <= rsi14 <= 48 and volume_ratio >= 1.05:
        technical_signal = "SHORT"
        reasons.extend([
            "Price and EMA20 are below EMA50",
            "RSI confirms bearish momentum",
            "Volume is above its recent average",
        ])
    else:
        reasons.append("No high-confidence technical setup yet")

    news = get_news_sentiment()
    signal = technical_signal

    # News is a confirmation/risk filter, never a standalone trading trigger.
    if technical_signal == "LONG" and news["label"] == "NEGATIVE":
        signal = "WAIT"
        reasons.append("Negative news sentiment conflicts with LONG setup")
    elif technical_signal == "SHORT" and news["label"] == "POSITIVE":
        signal = "WAIT"
        reasons.append("Positive news sentiment conflicts with SHORT setup")
    elif technical_signal in ("LONG", "SHORT"):
        reasons.append(f'News sentiment: {news["label"]} ({news["score"]:+d})')

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
        "technical_signal": technical_signal,
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "volume_ratio": volume_ratio,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "reasons": reasons,
        "news": news,
    }


last_signal = None

while True:
    analysis = analyze_market()

    if analysis:
        signal = analysis["signal"]
        print(
            f'BTCUSDT: {analysis["price"]:.2f} | Signal: {signal} | '
            f'RSI: {analysis["rsi"]:.1f} | News: {analysis["news"]["label"]}'
        )

        if signal in ("LONG", "SHORT") and signal != last_signal:
            news_titles = analysis["news"]["headlines"]
            news_text = "\n".join(f"- {title}" for title in news_titles) if news_titles else "No relevant headlines found"

            message = (
                f'BTC/USDT SIGNAL: {signal}\n'
                f'Entry reference: {analysis["price"]:.2f}\n'
                f'Stop Loss: {analysis["stop_loss"]:.2f}\n'
                f'Take Profit: {analysis["take_profit"]:.2f}\n'
                f'RSI(14): {analysis["rsi"]:.1f}\n'
                f'Volume ratio: {analysis["volume_ratio"]:.2f}x\n'
                f'News sentiment: {analysis["news"]["label"]} ({analysis["news"]["score"]:+d})\n'
                f'Why: {"; ".join(analysis["reasons"])}\n\n'
                f'Recent relevant headlines:\n{news_text}\n\n'
                'Analysis alert only - no trade was executed.'
            )
            send_telegram_message(message)

        last_signal = signal

    time.sleep(60)
