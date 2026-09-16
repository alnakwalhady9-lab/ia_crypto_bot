import os
import time
import requests

TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY=os.getenv("TWELVE_DATA_API_KEY")
TD_URL="https://api.twelvedata.com/time_series"
REPORT_SECONDS=900
CACHE_TTL={"5min":60,"15min":180,"1h":600}
cache={}


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: print("Telegram settings are missing"); return
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",data={"chat_id":TELEGRAM_CHAT_ID,"text":message},timeout=10);r.raise_for_status();print("Telegram message sent")
    except requests.RequestException as e: print(f"Telegram error: {e}")


def ema(v,p):
    k=2/(p+1);x=v[0]
    for n in v[1:]:x=n*k+x*(1-k)
    return x


def rsi(v,p=14):
    if len(v)<=p:return None
    d=[v[i]-v[i-1] for i in range(1,len(v))];g=[max(x,0) for x in d[-p:]];l=[max(-x,0) for x in d[-p:]]
    ag=sum(g)/p;al=sum(l)/p
    return 100.0 if al==0 else 100-(100/(1+ag/al))


def atr(c,p=14):
    if len(c)<=p:return None
    tr=[]
    for i in range(1,len(c)):
        h,l,pc=c[i]["high"],c[i]["low"],c[i-1]["close"];tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(tr[-p:])/p


def fetch_series(symbol,interval,outputsize=200,ttl=None):
    key=f"{symbol}:{interval}:{outputsize}";now=time.time()
    if key in cache and now-cache[key][0]<(ttl or CACHE_TTL.get(interval,120)):return cache[key][1]
    if not TWELVE_DATA_API_KEY:return None
    try:
        r=requests.get(TD_URL,params={"symbol":symbol,"interval":interval,"outputsize":outputsize,"apikey":TWELVE_DATA_API_KEY,"format":"JSON"},timeout=15,headers={"User-Agent":"gold-scalper/1.2"});r.raise_for_status();d=r.json()
        if d.get("status")=="error":print(f'Twelve Data error {symbol} {interval}: {d.get("message")}');return None
        rows=[]
        for x in reversed(d.get("values",[])):
            try:rows.append({"time":x.get("datetime"),"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"])})
            except (KeyError,TypeError,ValueError):pass
        if rows:cache[key]=(now,rows)
        return rows or None
    except (requests.RequestException,ValueError) as e:print(f"Data error {symbol} {interval}: {e}");return None


def snapshot(c):
    if not c or len(c)<55:return None
    closed=c[:-1];v=[x["close"] for x in closed]
    return {"price":v[-1],"ema9":ema(v[-40:],9),"ema20":ema(v[-50:],20),"ema50":ema(v[-55:],50),"rsi":rsi(v),"atr":atr(closed),"candles":closed}


def trend(s):
    if s["price"]>s["ema9"]>s["ema20"]>s["ema50"]:return "BULLISH"
    if s["price"]<s["ema9"]<s["ema20"]<s["ema50"]:return "BEARISH"
    return "MIXED"


def usd_strength():
    # USD proxy: falling EUR/USD + rising USD/JPY = stronger dollar; opposite = weaker dollar.
    eur=fetch_series("EUR/USD","15min",60,300);jpy=fetch_series("USD/JPY","15min",60,300)
    if not eur or not jpy or len(eur)<25 or len(jpy)<25:return "UNKNOWN"
    e=[x["close"] for x in eur[:-1]];j=[x["close"] for x in jpy[:-1]]
    efast,eslow=ema(e[-25:],9),ema(e[-25:],20);jfast,jslow=ema(j[-25:],9),ema(j[-25:],20)
    if efast<eslow and jfast>jslow:return "STRONG"
    if efast>eslow and jfast<jslow:return "WEAK"
    return "MIXED"


def analyze():
    s5=snapshot(fetch_series("XAU/USD","5min"));s15=snapshot(fetch_series("XAU/USD","15min"));s1h=snapshot(fetch_series("XAU/USD","1h"))
    if not all((s5,s15,s1h)):return None
    t5,t15,t1h=trend(s5),trend(s15),trend(s1h);price,r=s5["price"],s5["rsi"];usd=usd_strength()
    recent=s5["candles"][-20:];support=min(x["low"] for x in recent);resistance=max(x["high"] for x in recent)
    a=s5["atr"] or price*.001; ranges=[x["high"]-x["low"] for x in s5["candles"][-15:-1]]
    normal_range=sum(ranges)/len(ranges) if ranges else a;last=s5["candles"][-1];last_range=last["high"]-last["low"]
    news_risk=last_range>max(normal_range*2.4,a*2.0)  # abnormal volatility protection around surprise/news spikes
    side="WAIT";score=0;reasons=[]
    if t5=="BULLISH" and r is not None and 52<=r<=70:
        side,score="BUY",45;reasons.append("زخم 5 دقائق صاعد")
        if t15=="BULLISH":score+=20;reasons.append("15 دقيقة تؤكد الشراء")
        if t1h=="BULLISH":score+=15;reasons.append("اتجاه الساعة صاعد")
        if usd=="WEAK":score+=10;reasons.append("الدولار ضعيف ويدعم الذهب")
        elif usd=="STRONG":score-=15;reasons.append("الدولار قوي ويعارض شراء الذهب")
        if price>resistance-a*.20:score-=5;reasons.append("السعر قريب من المقاومة")
    elif t5=="BEARISH" and r is not None and 30<=r<=48:
        side,score="SELL",45;reasons.append("زخم 5 دقائق هابط")
        if t15=="BEARISH":score+=20;reasons.append("15 دقيقة تؤكد البيع")
        if t1h=="BEARISH":score+=15;reasons.append("اتجاه الساعة هابط")
        if usd=="STRONG":score+=10;reasons.append("الدولار قوي ويدعم هبوط الذهب")
        elif usd=="WEAK":score-=15;reasons.append("الدولار ضعيف ويعارض بيع الذهب")
        if price<support+a*.20:score-=5;reasons.append("السعر قريب من الدعم")
    score=max(0,min(100,score))
    if news_risk:
        reasons.append("حركة غير طبيعية/احتمال خبر قوي — تم إيقاف الدخول مؤقتًا");side="WAIT"
    elif score<70:side="WAIT"
    sl=price-1.15*a if side=="BUY" else price+1.15*a if side=="SELL" else None
    tp=price+1.75*a if side=="BUY" else price-1.75*a if side=="SELL" else None
    return {"side":side,"price":price,"rsi":r,"atr":a,"support":support,"resistance":resistance,"score":score,"t5":t5,"t15":t15,"t1h":t1h,"usd":usd,"news_risk":news_risk,"sl":sl,"tp":tp,"reasons":reasons}


def ar_side(v):return {"BUY":"🟢 شراء","SELL":"🔴 بيع","WAIT":"🟡 انتظار"}.get(v,v)
def ar_trend(v):return {"BULLISH":"صاعد 📈","BEARISH":"هابط 📉","MIXED":"مختلط ↔️"}.get(v,v)
def ar_usd(v):return {"STRONG":"قوي 💵⬆️","WEAK":"ضعيف 💵⬇️","MIXED":"مختلط ↔️","UNKNOWN":"غير متاح"}.get(v,v)

def message(a):
    risk="لا يوجد دخول حاليًا" if a["side"]=="WAIT" else f'🛑 وقف الخسارة: {a["sl"]:.2f}\n🏁 الهدف: {a["tp"]:.2f}'
    why="؛ ".join(a["reasons"]) or "لا توجد فرصة سكالبنج مؤكدة"
    protection="🔴 مفعّل" if a["news_risk"] else "🟢 طبيعي"
    return f'🥇 بوت الذهب XAU/USD — سكالبنج\n\n🎯 الإشارة: {ar_side(a["side"])}\n💰 السعر: {a["price"]:.2f}\n📌 الثقة: {a["score"]}%\n📈 RSI: {a["rsi"]:.1f}\n🌊 ATR: {a["atr"]:.2f}\n🟢 الدعم: {a["support"]:.2f}\n🔴 المقاومة: {a["resistance"]:.2f}\n💵 قوة الدولار: {ar_usd(a["usd"])}\n🛡️ حماية التقلب/الأخبار: {protection}\n\n⏱ الاتجاهات:\n5 دقائق: {ar_trend(a["t5"])}\n15 دقيقة: {ar_trend(a["t15"])}\nساعة: {ar_trend(a["t1h"])}\n\n{risk}\n🧠 السبب: {why}\n\n⚠️ تنبيه تحليلي فقط — لم يتم تنفيذ أي صفقة.'

last_signal=None;last_report=0
while True:
    a=analyze()
    if a:
        now=time.time();print(f'XAU/USD {a["price"]:.2f} | {a["side"]} | USD {a["usd"]} | risk {a["news_risk"]} | confidence {a["score"]}%')
        periodic=last_report==0 or now-last_report>=REPORT_SECONDS;immediate=a["side"] in ("BUY","SELL") and a["side"]!=last_signal
        if periodic or immediate:
            send_telegram(message(a))
            if periodic:last_report=now
        last_signal=a["side"]
    time.sleep(30)