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
REPORT_SECONDS = 900
POSITIVE_WORDS = {"approval","approved","adoption","bullish","surge","rally","record","inflows","buying","growth","breakout","launch","partnership","easing","buy","moon","pump","support","recovery","rebound"}
NEGATIVE_WORDS = {"hack","hacked","exploit","ban","lawsuit","crackdown","bearish","plunge","selloff","outflows","liquidation","fraud","breach","rejection","tightening","sell","dump","crash","fear","resistance","scam"}
BTC_NEWS_WORDS = {"bitcoin","btc","crypto","cryptocurrency","etf","sec","fed","federal reserve","inflation","interest rate","rates","cpi","tariff","regulation"}
reddit_cache={"timestamp":0,"data":None}

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing"); return
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",data={"chat_id":TELEGRAM_CHAT_ID,"text":message},timeout=10); r.raise_for_status(); print("Telegram message sent successfully")
    except requests.exceptions.RequestException as e: print(f"Telegram error: {e}")

def get_market_candles(granularity=900,limit=100):
    try:
        r=requests.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",params={"granularity":granularity},timeout=10,headers={"User-Agent":"ia-crypto-bot/1.5","Accept":"application/json"}); r.raise_for_status(); rows=r.json()
        if not isinstance(rows,list): return None
        rows.sort(key=lambda x:x[0]); return rows[-limit:]
    except (requests.exceptions.RequestException,ValueError) as e: print(f"Coinbase market API error ({granularity}s): {e}"); return None

def build_4h_candles(hourly):
    if not hourly:return None
    buckets={}
    for row in hourly:
        ts=int(row[0]); bucket=ts-(ts%14400); buckets.setdefault(bucket,[]).append(row)
    result=[]
    for bucket in sorted(buckets):
        group=sorted(buckets[bucket],key=lambda x:x[0])
        if len(group)!=4:continue
        result.append([bucket,min(float(x[1]) for x in group),max(float(x[2]) for x in group),float(group[0][3]),float(group[-1][4]),sum(float(x[5]) for x in group)])
    return result

def ema(values,period):
    m=2/(period+1); result=values[0]
    for value in values[1:]:result=value*m+result*(1-m)
    return result

def rsi(values,period=14):
    if len(values)<=period:return None
    gains=[];losses=[]
    for i in range(1,len(values)):
        change=values[i]-values[i-1];gains.append(max(change,0));losses.append(max(-change,0))
    ag=sum(gains[-period:])/period;al=sum(losses[-period:])/period
    return 100.0 if al==0 else 100-100/(1+ag/al)

def atr(candles,period=14):
    if len(candles)<=period:return None
    trs=[]
    for i in range(1,len(candles)):
        h,l,pc=float(candles[i][2]),float(candles[i][1]),float(candles[i-1][4]);trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs[-period:])/period

def timeframe_snapshot(candles):
    if not candles or len(candles)<51:return None
    closed=candles[:-1];closes=[float(c[4]) for c in closed]
    return {"price":closes[-1],"ema20":ema(closes[-50:],20),"ema50":ema(closes[-50:],50),"rsi":rsi(closes,14)}

def trend_of(s):
    if s["price"]>s["ema20"]>s["ema50"]:return "BULLISH"
    if s["price"]<s["ema20"]<s["ema50"]:return "BEARISH"
    return "MIXED"

def clean_text(text):return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",text or "")).strip()

def score_texts(texts):
    score=0
    for item in texts:
        text=item.lower();score+=sum(1 for w in POSITIVE_WORDS if w in text);score-=sum(1 for w in NEGATIVE_WORDS if w in text)
    return ("POSITIVE" if score>=2 else "NEGATIVE" if score<=-2 else "NEUTRAL"),score

def get_news_sentiment():
    headlines=[]
    for url in NEWS_FEEDS:
        try:
            r=requests.get(url,timeout=10,headers={"User-Agent":"Mozilla/5.0 ia-crypto-bot/1.5"});r.raise_for_status();root=ET.fromstring(r.content)
            for item in root.findall(".//item")[:15]:
                title,desc=clean_text(item.findtext("title")),clean_text(item.findtext("description"))
                if any(w in f"{title} {desc}".lower() for w in BTC_NEWS_WORDS):headlines.append(title)
        except (requests.exceptions.RequestException,ET.ParseError) as e:print(f"News feed error ({url}): {e}")
    headlines=list(dict.fromkeys(headlines))[:20];label,score=score_texts(headlines);return {"label":label,"score":score,"headlines":headlines[:3]}

def fetch_reddit_sentiment():
    posts=[];successful=0
    for url in REDDIT_FEEDS:
        try:
            r=requests.get(url,timeout=10,headers={"User-Agent":"ia-crypto-bot/1.5 by market-research-bot","Accept":"application/atom+xml,application/rss+xml"})
            if r.status_code==429:print(f"Reddit rate limited ({url}); skipping this feed");continue
            r.raise_for_status();successful+=1;root=ET.fromstring(r.content)
            for entry in root.iter():
                if entry.tag.endswith("entry"):
                    title=next((clean_text(c.text) for c in entry if c.tag.endswith("title")),"")
                    if title and any(w in title.lower() for w in ("bitcoin","btc","market","crypto")):posts.append(title)
        except (requests.exceptions.RequestException,ET.ParseError) as e:print(f"Reddit feed error ({url}): {e}")
    if successful==0:return {"label":"UNAVAILABLE","score":0,"posts":[],"available":False}
    posts=list(dict.fromkeys(posts))[:20];label,score=score_texts(posts);return {"label":label,"score":score,"posts":posts[:3],"available":True}

def get_reddit_sentiment():
    now=time.time()
    if reddit_cache["data"] is not None and now-reddit_cache["timestamp"]<REDDIT_CACHE_SECONDS:return reddit_cache["data"]
    reddit_cache["data"]=fetch_reddit_sentiment();reddit_cache["timestamp"]=now;return reddit_cache["data"]

def analyze_market():
    c15=get_market_candles(900,100);c1h=get_market_candles(3600,300);c4h=build_4h_candles(c1h)
    if not c15 or not c1h or not c4h:return None
    s15,s1h,s4h=timeframe_snapshot(c15),timeframe_snapshot(c1h),timeframe_snapshot(c4h)
    if not s15 or not s1h or not s4h:return None
    closed15=c15[:-1];volumes=[float(c[5]) for c in closed15];price,rsi14=s15["price"],s15["rsi"];avg_volume=sum(volumes[-21:-1])/20;volume_ratio=volumes[-1]/avg_volume if avg_volume else 0;atr14=atr(closed15,14)
    recent=closed15[-20:];support=min(float(c[1]) for c in recent);resistance=max(float(c[2]) for c in recent);t15,t1h,t4h=trend_of(s15),trend_of(s1h),trend_of(s4h)
    technical_signal,points,reasons="WAIT",0,[]
    if t15=="BULLISH" and rsi14 is not None and 52<=rsi14<=70 and volume_ratio>=1.05:technical_signal,points="LONG",60;reasons.extend(["15m bullish EMA structure","Bullish RSI momentum","Volume confirmation"])
    elif t15=="BEARISH" and rsi14 is not None and 30<=rsi14<=48 and volume_ratio>=1.05:technical_signal,points="SHORT",60;reasons.extend(["15m bearish EMA structure","Bearish RSI momentum","Volume confirmation"])
    else:reasons.append("No high-confidence 15m setup yet")
    if technical_signal=="LONG":
        if t1h=="BULLISH":points+=10;reasons.append("1h trend confirms LONG")
        elif t1h=="BEARISH":points-=15;reasons.append("1h trend conflicts with LONG")
        if t4h=="BULLISH":points+=10;reasons.append("4h trend confirms LONG")
        elif t4h=="BEARISH":points-=15;reasons.append("4h trend conflicts with LONG")
    elif technical_signal=="SHORT":
        if t1h=="BEARISH":points+=10;reasons.append("1h trend confirms SHORT")
        elif t1h=="BULLISH":points-=15;reasons.append("1h trend conflicts with SHORT")
        if t4h=="BEARISH":points+=10;reasons.append("4h trend confirms SHORT")
        elif t4h=="BULLISH":points-=15;reasons.append("4h trend conflicts with SHORT")
    news,reddit=get_news_sentiment(),get_reddit_sentiment();confidence=points
    if technical_signal=="LONG":
        confidence+=10 if news["label"]=="POSITIVE" else -15 if news["label"]=="NEGATIVE" else 0
        if reddit["available"]:confidence+=5 if reddit["label"]=="POSITIVE" else -5 if reddit["label"]=="NEGATIVE" else 0
    elif technical_signal=="SHORT":
        confidence+=10 if news["label"]=="NEGATIVE" else -15 if news["label"]=="POSITIVE" else 0
        if reddit["available"]:confidence+=5 if reddit["label"]=="NEGATIVE" else -5 if reddit["label"]=="POSITIVE" else 0
    confidence=max(0,min(100,confidence));signal=technical_signal if technical_signal in ("LONG","SHORT") and confidence>=70 else "WAIT"
    if technical_signal in ("LONG","SHORT") and signal=="WAIT":reasons.append("Combined confidence below 70%")
    risk=max(atr14*1.5,price*0.003) if atr14 else price*0.01;sl=price-risk if signal=="LONG" else price+risk if signal=="SHORT" else None;tp=price+risk*2 if signal=="LONG" else price-risk*2 if signal=="SHORT" else None
    return {"signal":signal,"price":price,"rsi":rsi14,"volume_ratio":volume_ratio,"atr":atr14,"support":support,"resistance":resistance,"trends":{"15m":t15,"1h":t1h,"4h":t4h},"stop_loss":sl,"take_profit":tp,"reasons":reasons,"news":news,"reddit":reddit,"confidence":confidence}

def ar_signal(v):return {"LONG":"🟢 شراء","SHORT":"🔴 بيع","WAIT":"🟡 انتظار"}.get(v,v)
def ar_trend(v):return {"BULLISH":"صاعد 📈","BEARISH":"هابط 📉","MIXED":"مختلط ↔️"}.get(v,v)
def ar_sentiment(v):return {"POSITIVE":"إيجابي","NEGATIVE":"سلبي","NEUTRAL":"محايد","UNAVAILABLE":"غير متاح"}.get(v,v)
def ar_reason(v):
    translations={"15m bullish EMA structure":"ترتيب المتوسطات على 15 دقيقة صاعد","Bullish RSI momentum":"زخم RSI إيجابي","Volume confirmation":"حجم التداول يؤكد الحركة","15m bearish EMA structure":"ترتيب المتوسطات على 15 دقيقة هابط","Bearish RSI momentum":"زخم RSI سلبي","No high-confidence 15m setup yet":"لا توجد فرصة مؤكدة على فريم 15 دقيقة حاليًا","1h trend confirms LONG":"اتجاه الساعة يؤكد الشراء","1h trend conflicts with LONG":"اتجاه الساعة يعارض الشراء","4h trend confirms LONG":"اتجاه 4 ساعات يؤكد الشراء","4h trend conflicts with LONG":"اتجاه 4 ساعات يعارض الشراء","1h trend confirms SHORT":"اتجاه الساعة يؤكد البيع","1h trend conflicts with SHORT":"اتجاه الساعة يعارض البيع","4h trend confirms SHORT":"اتجاه 4 ساعات يؤكد البيع","4h trend conflicts with SHORT":"اتجاه 4 ساعات يعارض البيع","Combined confidence below 70%":"الثقة المجمعة أقل من 70%"}
    return translations.get(v,v)

def report_message(a):
    reasons="؛ ".join(ar_reason(x) for x in a["reasons"])
    return (f'📊 تقرير البيتكوين - كل 15 دقيقة\n\n💰 السعر: ${a["price"]:.2f}\n🎯 القرار: {ar_signal(a["signal"])}\n📌 نسبة الثقة: {a["confidence"]}%\n📈 RSI: {a["rsi"]:.1f}\n🌊 ATR: {a["atr"]:.2f}\n🟢 الدعم: ${a["support"]:.2f}\n🔴 المقاومة: ${a["resistance"]:.2f}\n\n⏱ الاتجاهات:\n15 دقيقة: {ar_trend(a["trends"]["15m"])}\nساعة: {ar_trend(a["trends"]["1h"])}\n4 ساعات: {ar_trend(a["trends"]["4h"])}\n\n📦 حجم التداول: {a["volume_ratio"]:.2f}x\n📰 الأخبار: {ar_sentiment(a["news"]["label"])}\n💬 ريديت: {ar_sentiment(a["reddit"]["label"])}\n🧠 السبب: {reasons}\n\n⚠️ تحليل وتنبيه فقط — لم يتم تنفيذ أي صفقة.')

last_signal=None;last_report=0
while True:
    a=analyze_market()
    if a:
        signal=a["signal"];now=time.time();print(f'BTC-USD: {a["price"]:.2f} | Signal: {signal} | RSI: {a["rsi"]:.1f} | 15m/1h/4h: {a["trends"]["15m"]}/{a["trends"]["1h"]}/{a["trends"]["4h"]} | ATR: {a["atr"]:.2f} | S/R: {a["support"]:.0f}/{a["resistance"]:.0f} | News: {a["news"]["label"]} | Reddit: {a["reddit"]["label"]} | Confidence: {a["confidence"]}%')
        if signal in ("LONG","SHORT") and signal!=last_signal:
            reasons="؛ ".join(ar_reason(x) for x in a["reasons"])
            msg=(f'🚨 إشارة بيتكوين جديدة\n\n🎯 الإشارة: {ar_signal(signal)}\n💰 سعر الدخول المرجعي: ${a["price"]:.2f}\n🛑 وقف الخسارة: ${a["stop_loss"]:.2f}\n🏁 الهدف: ${a["take_profit"]:.2f}\n📌 نسبة الثقة: {a["confidence"]}%\n📈 RSI: {a["rsi"]:.1f}\n🌊 ATR: {a["atr"]:.2f}\n🟢 الدعم: ${a["support"]:.2f}\n🔴 المقاومة: ${a["resistance"]:.2f}\n⏱ 15د/1س/4س: {ar_trend(a["trends"]["15m"])} / {ar_trend(a["trends"]["1h"])} / {ar_trend(a["trends"]["4h"])}\n📰 الأخبار: {ar_sentiment(a["news"]["label"])}\n💬 ريديت: {ar_sentiment(a["reddit"]["label"])}\n🧠 السبب: {reasons}\n\n⚠️ تنبيه تحليلي فقط — لم يتم تنفيذ أي صفقة.');send_telegram_message(msg)
        if last_report==0 or now-last_report>=REPORT_SECONDS:
            send_telegram_message(report_message(a));last_report=now
        last_signal=signal
    time.sleep(60)