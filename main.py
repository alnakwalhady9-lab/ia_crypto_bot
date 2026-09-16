import os
import time
import re
import xml.etree.ElementTree as ET
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

NEWS_FEEDS = ["https://www.coindesk.com/arc/outboundfeeds/rss/", "https://cointelegraph.com/rss"]
REDDIT_FEEDS = ["https://www.reddit.com/r/Bitcoin/new/.rss", "https://www.reddit.com/r/CryptoCurrency/new/.rss"]
REDDIT_CACHE_SECONDS = 900

POSITIVE_WORDS = {"approval", "approved", "adoption", "bullish", "surge", "rally", "record", "inflows", "buying", "growth", "breakout", "launch", "partnership", "easing", "buy", "moon", "pump", "support", "recovery", "rebound"}
NEGATIVE_WORDS = {"hack", "hacked", "exploit", "ban", "lawsuit", "crackdown", "bearish", "plunge", "selloff", "outflows", "liquidation", "fraud", "breach", "rejection", "tightening", "sell", "dump", "crash", "fear", "resistance", "scam"}
BTC_NEWS_WORDS = {"bitcoin", "btc", "crypto", "cryptocurrency", "etf", "sec", "fed", "federal reserve", "inflation", "interest rate", "rates", "cpi", "tariff", "regulation"}
reddit_cache = {"timestamp": 0, "data": None}


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing")
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        r.raise_for_status()
        print("Telegram message sent successfully")
    except requests.exceptions.RequestException as e:
        print(f"Telegram error: {e}")


def get_market_candles(granularity=900, limit=100):
    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    try:
        r = requests.get(url, params={"granularity": granularity}, timeout=10, headers={"User-Agent": "ia-crypto-bot/1.2", "Accept": "application/json"})
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            return None
        rows.sort(key=lambda x: x[0])
        return rows[-limit:]
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Coinbase market API error ({granularity}s): {e}")
        return None


def ema(values, period):
    m = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * m + result * (1 - m)
    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0)); losses.append(max(-change, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def atr(candles, period=14):
    if len(candles) <= period:
        return None
    trs = []
    for i in range(1, len(candles)):
        high, low = float(candles[i][2]), float(candles[i][1])
        prev_close = float(candles[i - 1][4])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(trs[-period:]) / period


def timeframe_snapshot(candles):
    if not candles or len(candles) < 51:
        return None
    closed = candles[:-1]
    closes = [float(c[4]) for c in closed]
    return {"price": closes[-1], "ema20": ema(closes[-50:], 20), "ema50": ema(closes[-50:], 50), "rsi": rsi(closes, 14)}


def trend_of(snapshot):
    if snapshot["price"] > snapshot["ema20"] > snapshot["ema50"]:
        return "BULLISH"
    if snapshot["price"] < snapshot["ema20"] < snapshot["ema50"]:
        return "BEARISH"
    return "MIXED"


def clean_text(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def score_texts(texts):
    score = 0
    for item in texts:
        text = item.lower()
        score += sum(1 for w in POSITIVE_WORDS if w in text)
        score -= sum(1 for w in NEGATIVE_WORDS if w in text)
    return ("POSITIVE" if score >= 2 else "NEGATIVE" if score <= -2 else "NEUTRAL"), score


def get_news_sentiment():
    headlines = []
    for url in NEWS_FEEDS:
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 ia-crypto-bot/1.2"}); r.raise_for_status()
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:15]:
                title, desc = clean_text(item.findtext("title")), clean_text(item.findtext("description"))
                if any(w in f"{title} {desc}".lower() for w in BTC_NEWS_WORDS): headlines.append(title)
        except (requests.exceptions.RequestException, ET.ParseError) as e:
            print(f"News feed error ({url}): {e}")
    headlines = list(dict.fromkeys(headlines))[:20]
    label, score = score_texts(headlines)
    return {"label": label, "score": score, "headlines": headlines[:3]}


def fetch_reddit_sentiment():
    posts, successful = [], 0
    for url in REDDIT_FEEDS:
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "ia-crypto-bot/1.2 by market-research-bot", "Accept": "application/atom+xml,application/rss+xml"})
            if r.status_code == 429:
                print(f"Reddit rate limited ({url}); skipping this feed"); continue
            r.raise_for_status(); successful += 1
            root = ET.fromstring(r.content)
            for entry in root.iter():
                if entry.tag.endswith("entry"):
                    title = next((clean_text(c.text) for c in entry if c.tag.endswith("title")), "")
                    if title and any(w in title.lower() for w in ("bitcoin", "btc", "market", "crypto")): posts.append(title)
        except (requests.exceptions.RequestException, ET.ParseError) as e:
            print(f"Reddit feed error ({url}): {e}")
    if successful == 0: return {"label": "UNAVAILABLE", "score": 0, "posts": [], "available": False}
    posts = list(dict.fromkeys(posts))[:20]
    label, score = score_texts(posts)
    return {"label": label, "score": score, "posts": posts[:3], "available": True}


def get_reddit_sentiment():
    now = time.time()
    if reddit_cache["data"] is not None and now - reddit_cache["timestamp"] < REDDIT_CACHE_SECONDS: return reddit_cache["data"]
    reddit_cache["data"] = fetch_reddit_sentiment(); reddit_cache["timestamp"] = now
    return reddit_cache["data"]


def analyze_market():
    c15 = get_market_candles(900)
    c1h = get_market_candles(3600)
    c4h = get_market_candles(14400)
    if not c15 or not c1h or not c4h: return None
    s15, s1h, s4h = timeframe_snapshot(c15), timeframe_snapshot(c1h), timeframe_snapshot(c4h)
    if not s15 or not s1h or not s4h: return None

    closed15 = c15[:-1]
    volumes = [float(c[5]) for c in closed15]
    price, rsi14 = s15["price"], s15["rsi"]
    avg_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / avg_volume if avg_volume else 0
    atr14 = atr(closed15, 14)
    recent = closed15[-20:]
    support = min(float(c[1]) for c in recent)
    resistance = max(float(c[2]) for c in recent)
    t15, t1h, t4h = trend_of(s15), trend_of(s1h), trend_of(s4h)

    technical_signal, technical_points, reasons = "WAIT", 0, []
    if t15 == "BULLISH" and rsi14 is not None and 52 <= rsi14 <= 70 and volume_ratio >= 1.05:
        technical_signal, technical_points = "LONG", 60
        reasons.extend(["15m bullish EMA structure", "Bullish RSI momentum", "Volume confirmation"])
    elif t15 == "BEARISH" and rsi14 is not None and 30 <= rsi14 <= 48 and volume_ratio >= 1.05:
        technical_signal, technical_points = "SHORT", 60
        reasons.extend(["15m bearish EMA structure", "Bearish RSI momentum", "Volume confirmation"])
    else: reasons.append("No high-confidence 15m setup yet")

    if technical_signal == "LONG":
        if t1h == "BULLISH": technical_points += 10; reasons.append("1h trend confirms LONG")
        elif t1h == "BEARISH": technical_points -= 15; reasons.append("1h trend conflicts with LONG")
        if t4h == "BULLISH": technical_points += 10; reasons.append("4h trend confirms LONG")
        elif t4h == "BEARISH": technical_points -= 15; reasons.append("4h trend conflicts with LONG")
    elif technical_signal == "SHORT":
        if t1h == "BEARISH": technical_points += 10; reasons.append("1h trend confirms SHORT")
        elif t1h == "BULLISH": technical_points -= 15; reasons.append("1h trend conflicts with SHORT")
        if t4h == "BEARISH": technical_points += 10; reasons.append("4h trend confirms SHORT")
        elif t4h == "BULLISH": technical_points -= 15; reasons.append("4h trend conflicts with SHORT")

    news, reddit = get_news_sentiment(), get_reddit_sentiment()
    confidence = technical_points
    if technical_signal == "LONG":
        confidence += 10 if news["label"] == "POSITIVE" else -15 if news["label"] == "NEGATIVE" else 0
        if reddit["available"]: confidence += 5 if reddit["label"] == "POSITIVE" else -5 if reddit["label"] == "NEGATIVE" else 0
    elif technical_signal == "SHORT":
        confidence += 10 if news["label"] == "NEGATIVE" else -15 if news["label"] == "POSITIVE" else 0
        if reddit["available"]: confidence += 5 if reddit["label"] == "NEGATIVE" else -5 if reddit["label"] == "POSITIVE" else 0
    confidence = max(0, min(100, confidence))
    signal = technical_signal if technical_signal in ("LONG", "SHORT") and confidence >= 70 else "WAIT"
    if technical_signal in ("LONG", "SHORT") and signal == "WAIT": reasons.append("Combined confidence below 70%")

    # ATR adapts risk levels to current 15m volatility instead of a fixed percentage.
    risk = max(atr14 * 1.5, price * 0.003) if atr14 else price * 0.01
    stop_loss = price - risk if signal == "LONG" else price + risk if signal == "SHORT" else None
    take_profit = price + risk * 2 if signal == "LONG" else price - risk * 2 if signal == "SHORT" else None

    return {"signal": signal, "price": price, "rsi": rsi14, "volume_ratio": volume_ratio, "atr": atr14, "support": support, "resistance": resistance, "trends": {"15m": t15, "1h": t1h, "4h": t4h}, "stop_loss": stop_loss, "take_profit": take_profit, "reasons": reasons, "news": news, "reddit": reddit, "confidence": confidence}


last_signal = None
while True:
    a = analyze_market()
    if a:
        signal = a["signal"]
        print(f'BTC-USD: {a["price"]:.2f} | Signal: {signal} | RSI: {a["rsi"]:.1f} | 15m/1h/4h: {a["trends"]["15m"]}/{a["trends"]["1h"]}/{a["trends"]["4h"]} | ATR: {a["atr"]:.2f} | S/R: {a["support"]:.0f}/{a["resistance"]:.0f} | News: {a["news"]["label"]} | Reddit: {a["reddit"]["label"]} | Confidence: {a["confidence"]}%')
        if signal in ("LONG", "SHORT") and signal != last_signal:
            news_text = "\n".join(f"- {x}" for x in a["news"]["headlines"]) or "No relevant headlines found"
            reddit_text = ("\n".join(f"- {x}" for x in a["reddit"]["posts"]) or "No relevant Reddit posts found") if a["reddit"]["available"] else "Reddit unavailable/rate-limited; excluded from confidence"
            msg = (f'BTC/USD SIGNAL: {signal}\nEntry reference: {a["price"]:.2f}\nStop Loss: {a["stop_loss"]:.2f}\nTake Profit: {a["take_profit"]:.2f}\nConfidence: {a["confidence"]}%\nRSI(14): {a["rsi"]:.1f}\nATR(14): {a["atr"]:.2f}\nSupport: {a["support"]:.2f}\nResistance: {a["resistance"]:.2f}\nTrends 15m/1h/4h: {a["trends"]["15m"]}/{a["trends"]["1h"]}/{a["trends"]["4h"]}\nVolume ratio: {a["volume_ratio"]:.2f}x\nNews: {a["news"]["label"]} ({a["news"]["score"]:+d})\nReddit: {a["reddit"]["label"]}\nWhy: {"; ".join(a["reasons"])}\n\nNews:\n{news_text}\n\nReddit:\n{reddit_text}\n\nAnalysis alert only - no trade was executed.')
            send_telegram_message(msg)
        last_signal = signal
    time.sleep(60)
