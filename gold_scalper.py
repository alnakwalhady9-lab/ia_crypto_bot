import os,time,requests
TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN");TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID");TWELVE_DATA_API_KEY=os.getenv("TWELVE_DATA_API_KEY")
TD_URL="https://api.twelvedata.com/time_series";REPORT_SECONDS=900;CACHE_TTL={"5min":60,"15min":180,"1h":600};cache={}

def send_telegram(m):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:return
    try:r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",data={"chat_id":TELEGRAM_CHAT_ID,"text":m},timeout=10);r.raise_for_status()
    except requests.RequestException as e:print("Telegram",e)
def ema(v,p):
    k=2/(p+1);x=v[0]
    for n in v[1:]:x=n*k+x*(1-k)
    return x
def rsi(v,p=14):
    d=[v[i]-v[i-1] for i in range(1,len(v))];g=[max(x,0) for x in d[-p:]];l=[max(-x,0) for x in d[-p:]];ag=sum(g)/p;al=sum(l)/p
    return 100 if al==0 else 100-100/(1+ag/al)
def atr(c,p=14):
    tr=[]
    for i in range(1,len(c)):h,l,pc=c[i]["high"],c[i]["low"],c[i-1]["close"];tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(tr[-p:])/p if len(tr)>=p else None
def fetch_series(symbol,interval,outputsize=200,ttl=None):
    key=f"{symbol}:{interval}:{outputsize}";now=time.time()
    if key in cache and now-cache[key][0]<(ttl or CACHE_TTL.get(interval,120)):return cache[key][1]
    if not TWELVE_DATA_API_KEY:return None
    try:
        r=requests.get(TD_URL,params={"symbol":symbol,"interval":interval,"outputsize":outputsize,"apikey":TWELVE_DATA_API_KEY,"format":"JSON"},timeout=15);r.raise_for_status();d=r.json()
        if d.get("status")=="error":print("TD",d.get("message"));return None
        rows=[]
        for x in reversed(d.get("values",[])):
            try:rows.append({"time":x.get("datetime"),"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"])})
            except:pass
        if rows:cache[key]=(now,rows)
        return rows or None
    except Exception as e:print("Data",e);return None
def snapshot(c):
    if not c or len(c)<60:return None
    c=c[:-1];v=[x["close"] for x in c];return {"price":v[-1],"ema9":ema(v[-40:],9),"ema20":ema(v[-50:],20),"ema50":ema(v[-60:],50),"rsi":rsi(v),"atr":atr(c),"candles":c}
def trend(s):
    if s["price"]>s["ema9"]>s["ema20"]>s["ema50"]:return "BULLISH"
    if s["price"]<s["ema9"]<s["ema20"]<s["ema50"]:return "BEARISH"
    return "MIXED"
def pivots(c,left=3,right=3):
    out=[]
    for i in range(left,len(c)-right):
        h=c[i]["high"];l=c[i]["low"]
        if h==max(x["high"] for x in c[i-left:i+right+1]):out.append((i,h,"H"))
        if l==min(x["low"] for x in c[i-left:i+right+1]):out.append((i,l,"L"))
    out.sort();clean=[]
    for p in out:
        if clean and clean[-1][2]==p[2]:
            if (p[2]=="H" and p[1]>clean[-1][1]) or (p[2]=="L" and p[1]<clean[-1][1]):clean[-1]=p
        else:clean.append(p)
    return clean
def near(x,target,tol=.12):return target*(1-tol)<=x<=target*(1+tol)
def harmonic(c):
    ps=pivots(c[-120:]);best=None
    if len(ps)<5:return None
    for q in range(max(0,len(ps)-10),len(ps)-4):
        P=ps[q:q+5]
        if len(P)<5 or len({p[2] for p in P})<2:continue
        X,A,B,C,D=[p[1] for p in P];XA=abs(A-X);AB=abs(B-A);BC=abs(C-B);CD=abs(D-C);AD=abs(D-A)
        if min(XA,AB,BC,CD)==0:continue
        rAB=AB/XA;rBC=BC/AB;rCD=CD/BC;rAD=AD/XA;name=None
        if near(rAB,.618,.10) and .382<=rBC<=.886 and 1.13<=rCD<=1.75 and near(rAD,.786,.12):name="Gartley"
        elif .382<=rAB<=.50 and .382<=rBC<=.886 and 1.5<=rCD<=2.7 and near(rAD,.886,.12):name="Bat"
        elif near(rAB,.786,.12) and .382<=rBC<=.886 and 1.5<=rCD<=2.7 and 1.15<=rAD<=1.40:name="Butterfly"
        elif .382<=rAB<=.618 and .382<=rBC<=.886 and 2.0<=rCD<=3.8 and 1.45<=rAD<=1.75:name="Crab"
        elif .55<=AB/CD<=1.8 and .45<=BC/AB<=.9:name="ABCD"
        if name:
            side="BUY" if P[-1][2]=="L" else "SELL";best={"name":name,"side":side,"d":D,"ratios":(rAB,rBC,rCD,rAD)}
    return best
def divergence(c):
    ps=pivots(c[-80:],2,2);v=[x["close"] for x in c];rv=[]
    for i in range(15,len(v)):rv.append((i,rsi(v[:i+1])))
    lows=[p for p in ps if p[2]=="L"][-2:];highs=[p for p in ps if p[2]=="H"][-2:]
    if len(lows)==2:
        a,b=lows;ra=rsi(v[:a[0]+1]);rb=rsi(v[:b[0]+1])
        if ra is not None and rb is not None and b[1]<a[1] and rb>ra:return "BULLISH"
    if len(highs)==2:
        a,b=highs;ra=rsi(v[:a[0]+1]);rb=rsi(v[:b[0]+1])
        if ra is not None and rb is not None and b[1]>a[1] and rb<ra:return "BEARISH"
    return "NONE"
def usd_strength():
    e=fetch_series("EUR/USD","15min",60,300);j=fetch_series("USD/JPY","15min",60,300)
    if not e or not j:return "UNKNOWN"
    ev=[x["close"] for x in e[:-1]];jv=[x["close"] for x in j[:-1]]
    if ema(ev[-25:],9)<ema(ev[-25:],20) and ema(jv[-25:],9)>ema(jv[-25:],20):return "STRONG"
    if ema(ev[-25:],9)>ema(ev[-25:],20) and ema(jv[-25:],9)<ema(jv[-25:],20):return "WEAK"
    return "MIXED"
def analyze():
    s5=snapshot(fetch_series("XAU/USD","5min"));s15=snapshot(fetch_series("XAU/USD","15min"));s1=snapshot(fetch_series("XAU/USD","1h"))
    if not all((s5,s15,s1)):return None
    t5,t15,t1=trend(s5),trend(s15),trend(s1);h5=harmonic(s5["candles"]);h15=harmonic(s15["candles"]);div=divergence(s5["candles"]);usd=usd_strength();p=s5["price"];a=s5["atr"] or p*.001
    recent=s5["candles"][-20:];sup=min(x["low"] for x in recent);res=max(x["high"] for x in recent);score=0;buy=0;sell=0;reasons=[]
    if t5=="BULLISH":buy+=20
    elif t5=="BEARISH":sell+=20
    if t15=="BULLISH":buy+=20
    elif t15=="BEARISH":sell+=20
    if t1=="BULLISH":buy+=10
    elif t1=="BEARISH":sell+=10
    if h5:buy+=25 if h5["side"]=="BUY" else 0;sell+=25 if h5["side"]=="SELL" else 0;reasons.append(f'هارمونيك 5m: {h5["name"]} {h5["side"]}')
    if h15:buy+=20 if h15["side"]=="BUY" else 0;sell+=20 if h15["side"]=="SELL" else 0;reasons.append(f'هارمونيك 15m: {h15["name"]} {h15["side"]}')
    if div=="BULLISH":buy+=15;reasons.append("RSI دايفرجنس صاعد")
    elif div=="BEARISH":sell+=15;reasons.append("RSI دايفرجنس هابط")
    if usd=="WEAK":buy+=10
    elif usd=="STRONG":sell+=10
    ranges=[x["high"]-x["low"] for x in s5["candles"][-15:-1]];normal=sum(ranges)/len(ranges);spike=(s5["candles"][-1]["high"]-s5["candles"][-1]["low"])>max(normal*2.4,a*2)
    side="BUY" if buy>=70 and buy>=sell+20 else "SELL" if sell>=70 and sell>=buy+20 else "WAIT";score=max(buy,sell)
    if spike:side="WAIT";reasons.append("تقلب غير طبيعي — حماية الدخول مفعلة")
    if not reasons:reasons.append("لا يوجد توافق كافٍ بين أدوات التحليل")
    sl=p-1.15*a if side=="BUY" else p+1.15*a if side=="SELL" else None;tp1=p+1.2*a if side=="BUY" else p-1.2*a if side=="SELL" else None;tp2=p+1.8*a if side=="BUY" else p-1.8*a if side=="SELL" else None
    return {"side":side,"price":p,"score":min(score,100),"rsi":s5["rsi"],"atr":a,"support":sup,"resistance":res,"t5":t5,"t15":t15,"t1":t1,"h5":h5,"h15":h15,"div":div,"usd":usd,"spike":spike,"sl":sl,"tp1":tp1,"tp2":tp2,"reasons":reasons}
def ar(v):return {"BUY":"🟢 شراء","SELL":"🔴 بيع","WAIT":"🟡 انتظار","BULLISH":"صاعد 📈","BEARISH":"هابط 📉","MIXED":"مختلط ↔️","NONE":"لا يوجد","STRONG":"قوي","WEAK":"ضعيف","UNKNOWN":"غير متاح"}.get(v,v)
def message(a):
    h5=f'{a["h5"]["name"]} — {ar(a["h5"]["side"])}' if a["h5"] else "لا يوجد";h15=f'{a["h15"]["name"]} — {ar(a["h15"]["side"])}' if a["h15"] else "لا يوجد";risk="لا دخول حاليًا" if a["side"]=="WAIT" else f'🛑 SL: {a["sl"]:.2f}\n🎯 TP1: {a["tp1"]:.2f}\n🎯 TP2: {a["tp2"]:.2f}'
    return f'🥇 GOLD SCALPER PRO — XAU/USD\n\n🎯 القرار: {ar(a["side"])}\n💰 السعر: {a["price"]:.2f}\n⭐ قوة التوافق: {a["score"]}%\n📈 RSI: {a["rsi"]:.1f} | ATR: {a["atr"]:.2f}\n🟢 دعم: {a["support"]:.2f} | 🔴 مقاومة: {a["resistance"]:.2f}\n\n🧬 Harmonic 5m: {h5}\n🧬 Harmonic 15m: {h15}\n🔀 RSI Divergence: {ar(a["div"])}\n💵 الدولار: {ar(a["usd"])}\n\n⏱ 5m: {ar(a["t5"])} | 15m: {ar(a["t15"])} | 1h: {ar(a["t1"])}\n🛡️ حماية التقلب: {"مفعلة 🔴" if a["spike"] else "طبيعي 🟢"}\n\n{risk}\n🧠 السبب: {"؛ ".join(a["reasons"])}\n\n⚠️ تحليل احتمالي فقط — لا توجد صفقة منفذة.'
last_signal=None;last_report=0
while True:
    a=analyze()
    if a:
        now=time.time();print(f'XAU {a["price"]:.2f} {a["side"]} score={a["score"]} H5={a["h5"]} H15={a["h15"]}')
        periodic=last_report==0 or now-last_report>=REPORT_SECONDS;immediate=a["side"] in ("BUY","SELL") and a["side"]!=last_signal
        if periodic or immediate:send_telegram(message(a));last_report=now if periodic else last_report
        last_signal=a["side"]
    time.sleep(30)