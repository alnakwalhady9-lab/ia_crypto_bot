import os,time,re,xml.etree.ElementTree as ET,requests
TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN");TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")
NEWS_FEEDS=["https://www.coindesk.com/arc/outboundfeeds/rss/","https://cointelegraph.com/rss"]
REDDIT_FEEDS=["https://www.reddit.com/r/Bitcoin/new/.rss","https://www.reddit.com/r/CryptoCurrency/new/.rss"]
REPORT_SECONDS=900;REDDIT_CACHE_SECONDS=900;reddit_cache={"timestamp":0,"data":None}
POSITIVE_WORDS={"approval","approved","adoption","bullish","surge","rally","record","inflows","buying","growth","breakout","launch","partnership","easing","buy","moon","pump","support","recovery","rebound"}
NEGATIVE_WORDS={"hack","hacked","exploit","ban","lawsuit","crackdown","bearish","plunge","selloff","outflows","liquidation","fraud","breach","rejection","tightening","sell","dump","crash","fear","resistance","scam"}
BTC_NEWS_WORDS={"bitcoin","btc","crypto","cryptocurrency","etf","sec","fed","federal reserve","inflation","interest rate","rates","cpi","tariff","regulation"}
def send(m):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:return
    try:r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",data={"chat_id":TELEGRAM_CHAT_ID,"text":m},timeout=10);r.raise_for_status();print("Telegram message sent successfully")
    except Exception as e:print("Telegram",e)
def candles(g=900,limit=100):
    try:
        r=requests.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",params={"granularity":g},timeout=10,headers={"User-Agent":"ia-crypto-bot/1.6"});r.raise_for_status();x=r.json();x.sort(key=lambda z:z[0]);return x[-limit:]
    except Exception as e:print("Coinbase",e);return None
def build4(h):
    b={}
    for x in h or []:k=int(x[0])-(int(x[0])%14400);b.setdefault(k,[]).append(x)
    out=[]
    for k in sorted(b):
        z=sorted(b[k],key=lambda x:x[0])
        if len(z)==4:out.append([k,min(float(x[1]) for x in z),max(float(x[2]) for x in z),float(z[0][3]),float(z[-1][4]),sum(float(x[5]) for x in z)])
    return out
def ema(v,p):
    k=2/(p+1);a=v[0]
    for x in v[1:]:a=x*k+a*(1-k)
    return a
def rsi(v,p=14):
    d=[v[i]-v[i-1] for i in range(1,len(v))];g=sum(max(x,0) for x in d[-p:])/p;l=sum(max(-x,0) for x in d[-p:])/p
    return 100 if l==0 else 100-100/(1+g/l)
def atr(c,p=14):
    t=[]
    for i in range(1,len(c)):h,l,pc=float(c[i][2]),float(c[i][1]),float(c[i-1][4]);t.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(t[-p:])/p
def snap(c):
    if not c or len(c)<51:return None
    v=[float(x[4]) for x in c[:-1]];return {"price":v[-1],"e20":ema(v[-50:],20),"e50":ema(v[-50:],50),"rsi":rsi(v)}
def trend(s):
    if s["price"]>s["e20"]>s["e50"]:return "BULLISH"
    if s["price"]<s["e20"]<s["e50"]:return "BEARISH"
    return "MIXED"
def clean(x):return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",x or "")).strip()
def score_text(x):
    n=0
    for q in x:
        q=q.lower();n+=sum(w in q for w in POSITIVE_WORDS)-sum(w in q for w in NEGATIVE_WORDS)
    return "POSITIVE" if n>=2 else "NEGATIVE" if n<=-2 else "NEUTRAL"
def news():
    h=[]
    for u in NEWS_FEEDS:
        try:
            z=ET.fromstring(requests.get(u,timeout=8,headers={"User-Agent":"Mozilla/5.0"}).content)
            for i in z.findall(".//item")[:15]:
                q=clean(i.findtext("title"))+" "+clean(i.findtext("description"))
                if any(w in q.lower() for w in BTC_NEWS_WORDS):h.append(q)
        except Exception as e:print("News",e)
    return score_text(h)
def reddit():
    now=time.time()
    if reddit_cache["data"] and now-reddit_cache["timestamp"]<REDDIT_CACHE_SECONDS:return reddit_cache["data"]
    p=[]
    for u in REDDIT_FEEDS:
        try:
            r=requests.get(u,timeout=8,headers={"User-Agent":"ia-crypto-bot/1.6"});
            if r.status_code==200:
                root=ET.fromstring(r.content)
                for e in root.iter():
                    if e.tag.endswith("entry"):
                        t=next((clean(c.text) for c in e if c.tag.endswith("title")),"")
                        if t:p.append(t)
        except Exception as e:print("Reddit",e)
    x=score_text(p) if p else "UNAVAILABLE";reddit_cache.update(timestamp=now,data=x);return x
def analyze():
    c15=candles(900,100);c1=candles(3600,300);c4=build4(c1)
    s15,s1,s4=snap(c15),snap(c1),snap(c4)
    if not all((s15,s1,s4)):return None
    closed=c15[:-1];p=s15["price"];rr=s15["rsi"];a=atr(closed);vol=[float(x[5]) for x in closed];vr=vol[-1]/(sum(vol[-21:-1])/20 or 1);t15,t1,t4=trend(s15),trend(s1),trend(s4);n= news();rd=reddit();buy=sell=0
    # Directional bias is always calculated; it is NOT an entry signal by itself.
    if t15=="BULLISH":buy+=25
    elif t15=="BEARISH":sell+=25
    else:buy+=12;sell+=12
    if t1=="BULLISH":buy+=20
    elif t1=="BEARISH":sell+=20
    else:buy+=10;sell+=10
    if t4=="BULLISH":buy+=20
    elif t4=="BEARISH":sell+=20
    else:buy+=10;sell+=10
    if rr>=55:buy+=15
    elif rr<=45:sell+=15
    else:buy+=7.5;sell+=7.5
    if n=="POSITIVE":buy+=10
    elif n=="NEGATIVE":sell+=10
    else:buy+=5;sell+=5
    if rd=="POSITIVE":buy+=5
    elif rd=="NEGATIVE":sell+=5
    else:buy+=2.5;sell+=2.5
    if vr>=1.05:
        if t15=="BULLISH":buy+=15
        elif t15=="BEARISH":sell+=15
    total=buy+sell;buy_pct=round(100*buy/total) if total else 50;sell_pct=100-buy_pct
    signal="LONG" if buy_pct>=70 and t15=="BULLISH" and vr>=1.05 else "SHORT" if sell_pct>=70 and t15=="BEARISH" and vr>=1.05 else "WAIT"
    conf=max(buy_pct,sell_pct);recent=closed[-20:];sup=min(float(x[1]) for x in recent);res=max(float(x[2]) for x in recent);risk=max(a*1.5,p*.003);sl=p-risk if signal=="LONG" else p+risk if signal=="SHORT" else None;tp=p+risk*2 if signal=="LONG" else p-risk*2 if signal=="SHORT" else None
    return {"signal":signal,"price":p,"rsi":rr,"atr":a,"vr":vr,"sup":sup,"res":res,"t15":t15,"t1":t1,"t4":t4,"news":n,"reddit":rd,"buy":buy_pct,"sell":sell_pct,"confidence":conf,"sl":sl,"tp":tp}
def ars(x):return {"LONG":"🟢 شراء","SHORT":"🔴 بيع","WAIT":"🟡 انتظار"}.get(x,x)
def art(x):return {"BULLISH":"صاعد 📈","BEARISH":"هابط 📉","MIXED":"مختلط ↔️"}.get(x,x)
def sent(x):return {"POSITIVE":"إيجابي","NEGATIVE":"سلبي","NEUTRAL":"محايد","UNAVAILABLE":"غير متاح"}.get(x,x)
def report(a):
    return f'📊 تقرير البيتكوين - كل 15 دقيقة\n\n💰 السعر: ${a["price"]:.2f}\n🎯 القرار: {ars(a["signal"])}\n🟢 ميل الشراء: {a["buy"]}%\n🔴 ميل البيع: {a["sell"]}%\n📌 قوة الميل الأعلى: {a["confidence"]}%\n📈 RSI: {a["rsi"]:.1f}\n🌊 ATR: {a["atr"]:.2f}\n🟢 الدعم: ${a["sup"]:.2f}\n🔴 المقاومة: ${a["res"]:.2f}\n\n⏱ 15د: {art(a["t15"])} | 1س: {art(a["t1"])} | 4س: {art(a["t4"])}\n📦 الحجم: {a["vr"]:.2f}x\n📰 الأخبار: {sent(a["news"])}\n💬 ريديت: {sent(a["reddit"])}\n\n⚠️ نسب الميل تحليلية وليست احتمال نجاح أو ضمانًا. لا توجد صفقة منفذة.'
last_signal=None;last_report=0
while True:
    a=analyze()
    if a:
        now=time.time();print(f'BTC-USD: {a["price"]:.2f} | Signal: {a["signal"]} | BUY: {a["buy"]}% | SELL: {a["sell"]}% | RSI: {a["rsi"]:.1f} | 15m/1h/4h: {a["t15"]}/{a["t1"]}/{a["t4"]}')
        if a["signal"] in ("LONG","SHORT") and a["signal"]!=last_signal:
            send(f'🚨 إشارة بيتكوين جديدة\n\n🎯 {ars(a["signal"])}\n💰 ${a["price"]:.2f}\n🟢 شراء {a["buy"]}% | 🔴 بيع {a["sell"]}%\n🛑 SL: ${a["sl"]:.2f}\n🎯 TP: ${a["tp"]:.2f}\n⚠️ تنبيه تحليلي فقط — لم يتم تنفيذ صفقة.')
        if last_report==0 or now-last_report>=REPORT_SECONDS:send(report(a));last_report=now
        last_signal=a["signal"]
    time.sleep(60)