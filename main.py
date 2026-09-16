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


def get_market_candles():
    # Coinbase public Exchange candles are used because Binance returned HTTP 451 from Railway.
    # granularity=900 means 15-minute candles. Response: [time, low, high, open, close, volume].
    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    params = {"granularity": 900}
    try:
        response = requests.get(
            url,
            params=params,
            timeout=10,
            headers={"User-Agent": "ia-crypto-bot/1.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        candles = response.json()
        if not isinstance(candles, list):
            return None
        # Coinbase returns newest first; normalize to oldest -> newest.
        candles.sort(key=lambda row: row[0])
        return candles[-100:]
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Coinbase market API error: {e}")
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
    gains, losses = [], []
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
            response = requests.get(feed_url, timeout=10, headers={"User-Agent": "Mozilla/5.0 ia-crypto-bot/1.0"})
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

    headlines = list(dict.fromkeys(headlines))[:20]
    if not headlines:
        return {"label": "NEUTRAL", "score": 0, "headlines": []}

    score = 0
    for headline in headlines:
        text = headline.lower()
        score += sum(1 for word in POSITIVE_NEWS_WORDS if word in text)
        score -= sum(1 for word in NEGATIVE_NEWS_WORDS if word in text)

    label = "POSITIVE" if score >= 2 else "NEGATIVE" if score <= -2 else "NEUTRAL"
    return {"label": label, "score": score, "headlines": headlines[:3]}


def analyze_market():
    candles = get_market_candles()
    if not candles or len(candles) < 51:
        return None

    # Ignore newest candle because it may still be forming.
    closed = candles[:-1]
    closes = [float(c[4]) for c in closed]
    volumes = [float(c[5]) for c in closed]

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
        reasons.extend(["Price and EMA20 are above EMA50", "RSI confirms bullish momentum", "Volume is above its recent average"])
    elif price < ema20 < ema50 and rsi14 is not None and 30 <= rsi14 <= 48 and volume_ratio >= 1.05:
        technical_signal = "SHORT"
        reasons.extend(["Price and EMA20 are below EMA50", "RSI confirms bearish momentum", "Volume is above its recent average"])
    else:
        reasons.append("No high-confidence technical setup yet")

    news = get_news_sentiment()
    signal = technical_signal
    if technical_signal == "LONG" and news["label"] == "NEGATIVE":
        signal = "WAIT"
        reasons.append("Negative news sentiment conflicts with LONG setup")
    elif technical_signal == "SHORT" and news["label"] == "POSITIVE":
        signal = "WAIT"
        reasons.append("Positive news sentiment conflicts with SHORT setup")
    elif technical_signal in ("LONG", "SHORT"):
        reasons.append(f'News sentiment: {news["label"]} ({news["score"]:+d})')

    risk_distance = price * 0.01
    stop_loss = price - risk_distance if signal == "LONG" else price + risk_distance if signal == "SHORT" else None
    take_profit = price + 2 * risk_distance if signal == "LONG" else price - 2 * risk_distance if signal == "SHORT" else None

    return {
        "signal": signal, "price": price, "rsi": rsi14, "volume_ratio": volume_ratio,
        "stop_loss": stop_loss, "take_profit": take_profit, "reasons": reasons, "news": news,
    }


last_signal = None
while True:
    analysis = analyze_market()
    if analysis:
        signal = analysis["signal"]
        print(f'BTC-USD: {analysis["price"]:.2f} | Signal: {signal} | RSI: {analysis["rsi"]:.1f} | News: {analysis["news"]["label"]}')

        if signal in ("LONG", "SHORT") and signal != last_signal:
            news_titles = analysis["news"]["headlines"]
            news_text = "\n".join(f"- {title}" for title in news_titles) if news_titles else "No relevant headlines found"
            message = (
                f'BTC/USD SIGNAL: {signal}\nEntry reference: {analysis["price"]:.2f}\n'
                f'Stop Loss: {analysis["stop_loss"]:.2f}\nTake Profit: {analysis["take_profit"]:.2f}\n'
                f'RSI(14): {analysis["rsi"]:.1f}\nVolume ratio: {analysis["volume_ratio"]:.2f}x\n'
                f'News sentiment: {analysis["news"]["label"]} ({analysis["news"]["score"]:+d})\n'
                f'Why: {"; ".join(analysis["reasons"])}\n\nRecent relevant headlines:\n{news_text}\n\n'
                'Analysis alert only - no trade was executed.'
            )
            send_telegram_message(message)
        last_signal = signal
    time.sleep(60)
