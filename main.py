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
REDDIT_FEEDS = [
    "https://www.reddit.com/r/Bitcoin/new/.rss",
    "https://www.reddit.com/r/CryptoCurrency/new/.rss",
]
REDDIT_CACHE_SECONDS = 900  # refresh Reddit at most once every 15 minutes

POSITIVE_WORDS = {
    "approval", "approved", "adoption", "bullish", "surge", "rally", "record",
    "inflows", "buying", "growth", "breakout", "launch", "partnership", "easing",
    "buy", "moon", "pump", "support", "recovery", "rebound",
}
NEGATIVE_WORDS = {
    "hack", "hacked", "exploit", "ban", "lawsuit", "crackdown", "bearish", "plunge",
    "selloff", "outflows", "liquidation", "fraud", "breach", "rejection", "tightening",
    "sell", "dump", "crash", "fear", "resistance", "scam",
}
BTC_NEWS_WORDS = {
    "bitcoin", "btc", "crypto", "cryptocurrency", "etf", "sec", "fed", "federal reserve",
    "inflation", "interest rate", "rates", "cpi", "tariff", "regulation",
}

reddit_cache = {"timestamp": 0, "data": None}


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        response.raise_for_status()
        print("Telegram message sent successfully")
    except requests.exceptions.RequestException as e:
        print(f"Telegram error: {e}")


def get_market_candles():
    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    try:
        response = requests.get(url, params={"granularity": 900}, timeout=10,
                                headers={"User-Agent": "ia-crypto-bot/1.0", "Accept": "application/json"})
        response.raise_for_status()
        candles = response.json()
        if not isinstance(candles, list):
            return None
        candles.sort(key=lambda row: row[0])
        return candles[-100:]
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Coinbase market API error: {e}")
        return None


def ema(values, period):
    multiplier = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * multiplier + result * (1 - multiplier)
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
    return 100 - 100 / (1 + avg_gain / avg_loss)


def clean_text(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def score_texts(texts):
    score = 0
    for item in texts:
        text = item.lower()
        score += sum(1 for word in POSITIVE_WORDS if word in text)
        score -= sum(1 for word in NEGATIVE_WORDS if word in text)
    label = "POSITIVE" if score >= 2 else "NEGATIVE" if score <= -2 else "NEUTRAL"
    return label, score


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
                if any(word in f"{title} {description}".lower() for word in BTC_NEWS_WORDS):
                    headlines.append(title)
        except (requests.exceptions.RequestException, ET.ParseError) as e:
            print(f"News feed error ({feed_url}): {e}")
    headlines = list(dict.fromkeys(headlines))[:20]
    label, score = score_texts(headlines)
    return {"label": label, "score": score, "headlines": headlines[:3]}


def fetch_reddit_sentiment():
    posts = []
    successful_feeds = 0
    for feed_url in REDDIT_FEEDS:
        try:
            response = requests.get(
                feed_url,
                timeout=10,
                headers={"User-Agent": "ia-crypto-bot/1.1 by market-research-bot", "Accept": "application/atom+xml,application/rss+xml"},
            )
            if response.status_code == 429:
                print(f"Reddit rate limited ({feed_url}); skipping this feed")
                continue
            response.raise_for_status()
            successful_feeds += 1
            root = ET.fromstring(response.content)
            for entry in root.iter():
                if entry.tag.endswith("entry"):
                    title = ""
                    for child in entry:
                        if child.tag.endswith("title"):
                            title = clean_text(child.text)
                            break
                    if title and any(word in title.lower() for word in ("bitcoin", "btc", "market", "crypto")):
                        posts.append(title)
        except (requests.exceptions.RequestException, ET.ParseError) as e:
            print(f"Reddit feed error ({feed_url}): {e}")

    if successful_feeds == 0:
        return {"label": "UNAVAILABLE", "score": 0, "posts": [], "available": False}

    posts = list(dict.fromkeys(posts))[:20]
    label, score = score_texts(posts)
    return {"label": label, "score": score, "posts": posts[:3], "available": True}


def get_reddit_sentiment():
    now = time.time()
    cached = reddit_cache["data"]
    if cached is not None and now - reddit_cache["timestamp"] < REDDIT_CACHE_SECONDS:
        return cached

    fresh = fetch_reddit_sentiment()
    reddit_cache["timestamp"] = now
    reddit_cache["data"] = fresh
    return fresh


def analyze_market():
    candles = get_market_candles()
    if not candles or len(candles) < 51:
        return None

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
    technical_points = 0
    reasons = []
    if price > ema20 > ema50 and rsi14 is not None and 52 <= rsi14 <= 70 and volume_ratio >= 1.05:
        technical_signal = "LONG"
        technical_points = 70
        reasons.extend(["Bullish EMA structure", "Bullish RSI momentum", "Volume confirmation"])
    elif price < ema20 < ema50 and rsi14 is not None and 30 <= rsi14 <= 48 and volume_ratio >= 1.05:
        technical_signal = "SHORT"
        technical_points = 70
        reasons.extend(["Bearish EMA structure", "Bearish RSI momentum", "Volume confirmation"])
    else:
        reasons.append("No high-confidence technical setup yet")

    news = get_news_sentiment()
    reddit = get_reddit_sentiment()
    signal = technical_signal
    confidence = technical_points

    if technical_signal == "LONG":
        confidence += 15 if news["label"] == "POSITIVE" else -20 if news["label"] == "NEGATIVE" else 0
        if reddit["available"]:
            confidence += 15 if reddit["label"] == "POSITIVE" else -10 if reddit["label"] == "NEGATIVE" else 0
    elif technical_signal == "SHORT":
        confidence += 15 if news["label"] == "NEGATIVE" else -20 if news["label"] == "POSITIVE" else 0
        if reddit["available"]:
            confidence += 15 if reddit["label"] == "NEGATIVE" else -10 if reddit["label"] == "POSITIVE" else 0

    confidence = max(0, min(100, confidence))
    if technical_signal in ("LONG", "SHORT") and confidence < 70:
        signal = "WAIT"
        reasons.append("Context reduced confidence below alert threshold")

    if technical_signal in ("LONG", "SHORT"):
        reasons.append(f'News: {news["label"]} ({news["score"]:+d})')
        if reddit["available"]:
            reasons.append(f'Reddit: {reddit["label"]} ({reddit["score"]:+d})')
        else:
            reasons.append("Reddit unavailable; excluded from confidence")

    risk_distance = price * 0.01
    stop_loss = price - risk_distance if signal == "LONG" else price + risk_distance if signal == "SHORT" else None
    take_profit = price + 2 * risk_distance if signal == "LONG" else price - 2 * risk_distance if signal == "SHORT" else None

    return {
        "signal": signal, "price": price, "rsi": rsi14, "volume_ratio": volume_ratio,
        "stop_loss": stop_loss, "take_profit": take_profit, "reasons": reasons,
        "news": news, "reddit": reddit, "confidence": confidence,
    }


last_signal = None
while True:
    analysis = analyze_market()
    if analysis:
        signal = analysis["signal"]
        print(
            f'BTC-USD: {analysis["price"]:.2f} | Signal: {signal} | RSI: {analysis["rsi"]:.1f} | '
            f'News: {analysis["news"]["label"]} | Reddit: {analysis["reddit"]["label"]} | '
            f'Confidence: {analysis["confidence"]}%'
        )

        if signal in ("LONG", "SHORT") and signal != last_signal:
            news_text = "\n".join(f"- {x}" for x in analysis["news"]["headlines"]) or "No relevant headlines found"
            if analysis["reddit"]["available"]:
                reddit_text = "\n".join(f"- {x}" for x in analysis["reddit"]["posts"]) or "No relevant Reddit posts found"
            else:
                reddit_text = "Reddit unavailable/rate-limited; excluded from confidence"
            message = (
                f'BTC/USD SIGNAL: {signal}\nEntry reference: {analysis["price"]:.2f}\n'
                f'Stop Loss: {analysis["stop_loss"]:.2f}\nTake Profit: {analysis["take_profit"]:.2f}\n'
                f'Confidence: {analysis["confidence"]}%\nRSI(14): {analysis["rsi"]:.1f}\n'
                f'Volume ratio: {analysis["volume_ratio"]:.2f}x\n'
                f'News: {analysis["news"]["label"]} ({analysis["news"]["score"]:+d})\n'
                f'Reddit: {analysis["reddit"]["label"]}\n'
                f'Why: {"; ".join(analysis["reasons"])}\n\nNews:\n{news_text}\n\nReddit:\n{reddit_text}\n\n'
                'Analysis alert only - no trade was executed.'
            )
            send_telegram_message(message)
        last_signal = signal
    time.sleep(60)
