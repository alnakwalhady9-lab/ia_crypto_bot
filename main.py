import os,time,re,math,xml.etree.ElementTree as ET,requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN");CHAT=os.getenv("TELEGRAM_CHAT_ID");REPORT=900
PAPER_MODE=os.getenv("CRYPTO_PAPER_MODE","true").strip().lower() not in ("0","false","off","no")
STARTED_AT=time.time()
STARTUP_BLOCK_SECONDS=float(os.getenv("PAPER_STARTUP_BLOCK_SECONDS","21600"))
def env_float(name,default):
    try:return float(os.getenv(name,str(default)))
    except (TypeError,ValueError):return float(default)
# BTC paper-account risk model. Contract default: 1.0 lot = 1 BTC.
BTC_ACCOUNT_BALANCE=env_float("BTC_ACCOUNT_BALANCE",5000)
BTC_RISK_PCT=env_float("BTC_RISK_PCT",1.0)
BTC_SPREAD_USD=env_float("BTC_SPREAD_USD",30.0)
BTC_CONTRACT_BTC_PER_LOT=env_float("BTC_CONTRACT_BTC_PER_LOT",1.0)
BTC_LOT_STEP=env_float("BTC_LOT_STEP",0.01)
BTC_MIN_LOT=env_float("BTC_MIN_LOT",0.01)
BTC_MAX_LOT=env_float("BTC_MAX_LOT",1.0)
SESSION=requests.Session();_adapter=HTTPAdapter(pool_connections=10,pool_maxsize=10);SESSION.mount("https://",_adapter);SESSION.mount("http://",_adapter)
EXECUTOR=ThreadPoolExecutor(max_workers=3)
def run_with_timeout(fn,timeout,name):
    try:
        fut=EXECUTOR.submit(fn);return fut.result(timeout=timeout)
    except FutureTimeoutError:print(f"{name} TIMEOUT after {timeout}s");return None
    except Exception as e:print(f"{name} ERROR",e);return None
NEWS=["https://www.coindesk.com/arc/outboundfeeds/rss/","https://cointelegraph.com/rss/"];REDDIT=["https://www.reddit.com/r/Bitcoin/new/.rss","https://www.reddit.com/r/CryptoCurrency/new/.rss"]
POS={"approval","approved","adoption","bullish","surge","rally","record","inflows","buying","growth","breakout","easing","recovery","rebound"};NEG={"hack","exploit","ban","lawsuit","crackdown","bearish","plunge","selloff","outflows","liquidation","fraud","dump","crash","fear"};rc={"t":0,"v":"UNAVAILABLE"}
def send(m):
    if TOKEN and CHAT:
        try:requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",data={"chat_id":CHAT,"text":m},timeout=12).raise_for_status()
        except Exception as e:print("Telegram",e)
def candles(g,n):
    try:
        r=SESSION.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",params={"granularity":g},timeout=(5,10),headers={"User-Agent":"ia-crypto-bot/2.0"});r.raise_for_status();x=r.json();x.sort(key=lambda z:z[0]);return x[-n:]
    except Exception as e:print("Coinbase",e);return None
def eur_candles(interval="5m",limit=120):
    try:
        r=SESSION.get("https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X",params={"range":"5d","interval":interval,"includePrePost":"false"},timeout=(5,15),headers={"User-Agent":"Mozilla/5.0 ia-crypto-bot/2.3"});r.raise_for_status();j=r.json()["chart"]["result"][0];ts=j.get("timestamp",[]);q=j["indicators"]["quote"][0];out=[]
        for i,t in enumerate(ts):
            o=q["open"][i];h=q["high"][i];l=q["low"][i];c=q["close"][i]
            if None not in (o,h,l,c):out.append([int(t),float(l),float(h),float(o),float(c),0.0])
        return out[-limit:]
    except Exception as e:print("EURUSD feed",e);return None
def jpy_candles(interval="5m",limit=120):
    try:
        r=SESSION.get("https://query1.finance.yahoo.com/v8/finance/chart/JPY=X",params={"range":"5d","interval":interval,"includePrePost":"false"},timeout=(5,15),headers={"User-Agent":"Mozilla/5.0 ia-crypto-bot/3.0"});r.raise_for_status();j=r.json()["chart"]["result"][0];ts=j.get("timestamp",[]);q=j["indicators"]["quote"][0];out=[]
        for i,t in enumerate(ts):
            o=q["open"][i];h=q["high"][i];l=q["low"][i];c=q["close"][i]
            if None not in (o,h,l,c):out.append([int(t),float(l),float(h),float(o),float(c),0.0])
        return out[-limit:]
    except Exception as e:print("USDJPY feed",e);return None
def build4(h):
    b={}
    for x in h or []:k=int(x[0])-(int(x[0])%14400);b.setdefault(k,[]).append(x)
    o=[]
    for k in sorted(b):
        z=sorted(b[k],key=lambda q:q[0])
        if len(z)==4:o.append([k,min(float(q[1]) for q in z),max(float(q[2]) for q in z),float(z[0][3]),float(z[-1][4]),sum(float(q[5]) for q in z)])
    return o
def ema(v,p):
    k=2/(p+1);a=v[0]
    for x in v[1:]:a=x*k+a*(1-k)
    return a
def rsi(v,p=14):
    d=[v[i]-v[i-1] for i in range(1,len(v))];g=sum(max(x,0) for x in d[-p:])/p;l=sum(max(-x,0) for x in d[-p:])/p;return 100 if l==0 else 100-100/(1+g/l)
def atr(c,p=14):
    t=[]
    for i in range(1,len(c)):t.append(max(float(c[i][2])-float(c[i][1]),abs(float(c[i][2])-float(c[i-1][4])),abs(float(c[i][1])-float(c[i-1][4]))))
    return sum(t[-p:])/p
def snap(c):
    if not c or len(c)<55:return None
    c=c[:-1];v=[float(x[4]) for x in c];return {"p":v[-1],"e20":ema(v[-50:],20),"e50":ema(v[-50:],50),"r":rsi(v),"c":c}
def trend(s):return "UP" if s["p"]>s["e20"]>s["e50"] else "DOWN" if s["p"]<s["e20"]<s["e50"] else "MIXED"
def piv(c,L=2,R=2):
    o=[]
    for i in range(L,len(c)-R):
        h=float(c[i][2]);l=float(c[i][1]);w=c[i-L:i+R+1]
        if h==max(float(x[2]) for x in w):o.append((i,h,"H"))
        if l==min(float(x[1]) for x in w):o.append((i,l,"L"))
    return o
def structure(c):
    p=piv(c[-80:]);h=[x for x in p if x[2]=="H"][-2:];l=[x for x in p if x[2]=="L"][-2:]
    if len(h)==2 and len(l)==2:
        if h[-1][1]>h[-2][1] and l[-1][1]>l[-2][1]:return "UP"
        if h[-1][1]<h[-2][1] and l[-1][1]<l[-2][1]:return "DOWN"
    return "RANGE"
def liquidity(c):
    p=piv(c[-30:-1]);hs=[x[1] for x in p if x[2]=="H"];ls=[x[1] for x in p if x[2]=="L"];x=c[-1]
    sell=bool(hs and float(x[2])>max(hs) and float(x[4])<max(hs));buy=bool(ls and float(x[1])<min(ls) and float(x[4])>min(ls));return buy,sell
def sentiment(urls):
    texts=[]
    for u in urls:
        try:
            r=requests.get(u,timeout=8,headers={"User-Agent":"Mozilla/5.0 ia-bot"})
            if r.status_code!=200:continue
            root=ET.fromstring(r.content)
            for e in root.iter():
                if e.tag.endswith("title") and e.text:texts.append(re.sub(r"<[^>]+>"," ",e.text).lower())
        except Exception as e:print("Feed",e)
    n=sum(sum(w in q for w in POS)-sum(w in q for w in NEG) for q in texts[:30]);return "POSITIVE" if n>=2 else "NEGATIVE" if n<=-2 else "NEUTRAL"
def reddit():
    if time.time()-rc["t"]<900:return rc["v"]
    rc.update(t=time.time(),v=sentiment(REDDIT));return rc["v"]
def analyze():
    c15=candles(900,100);c1=candles(3600,300);c4=build4(c1);s15=snap(c15);s1=snap(c1);s4=snap(c4)
    if not all((s15,s1,s4)):return None
    c=s15["c"];p=s15["p"];a=atr(c);r=s15["r"];t15,t1,t4=trend(s15),trend(s1),trend(s4);st=structure(c);lb,ls=liquidity(c);vol=[float(x[5]) for x in c];vr=vol[-1]/(sum(vol[-21:-1])/20 or 1);recent=c[-20:];sup=min(float(x[1]) for x in recent);res=max(float(x[2]) for x in recent);n=sentiment(NEWS);rd=reddit();buy=sell=0;why=[]
    if t15=="UP":buy+=22
    elif t15=="DOWN":sell+=22
    if t1=="UP":buy+=15
    elif t1=="DOWN":sell+=15
    if t4=="UP":buy+=10
    elif t4=="DOWN":sell+=10
    if st=="UP":buy+=15;why.append("هيكل سعري صاعد")
    elif st=="DOWN":sell+=15;why.append("هيكل سعري هابط")
    if lb:buy+=18;why.append("Liquidity sweep أسفل قاع")
    if ls:sell+=18;why.append("Liquidity sweep أعلى قمة")
    if r>=55:buy+=10
    elif r<=45:sell+=10
    if vr>=1.05:
        if t15=="UP":buy+=10
        elif t15=="DOWN":sell+=10
    # News and Reddit are context only during the paper test. They must not
    # add points or change the technical direction.
    total=max(buy+sell,1);bp=round(100*buy/total);sp=100-bp;side="LONG" if bp>=65 and buy>=sell+15 else "SHORT" if sp>=65 and sell>=buy+15 else "WAIT"
    if side=="LONG" and res-p<1.10*a:side="WAIT";why.append("مقاومة قريبة — منع مطاردة السعر")
    if side=="SHORT" and p-sup<1.10*a:side="WAIT";why.append("دعم قريب — منع مطاردة السعر")
    risk=max(a*1.4,p*.0025)
    sl=p-risk if side=="LONG" else p+risk if side=="SHORT" else None
    tp=p+risk*2 if side=="LONG" else p-risk*2 if side=="SHORT" else None
    lot_size=0.0;dollar_risk=0.0;dollar_reward=0.0;risk_budget=BTC_ACCOUNT_BALANCE*BTC_RISK_PCT/100
    if side in ("LONG","SHORT"):
        # Size from the actual stop distance plus a conservative BTC spread.
        loss_per_lot=(abs(p-sl)+BTC_SPREAD_USD)*BTC_CONTRACT_BTC_PER_LOT
        raw_lot=risk_budget/loss_per_lot if loss_per_lot>0 else 0.0
        lot_size=math.floor(raw_lot/BTC_LOT_STEP+1e-12)*BTC_LOT_STEP if BTC_LOT_STEP>0 else 0.0
        lot_size=min(lot_size,BTC_MAX_LOT)
        if lot_size<BTC_MIN_LOT:
            side="WAIT";lot_size=0.0;why.append("حجم العقد الأدنى يتجاوز حد المخاطرة — لا دخول")
        else:
            dollar_risk=lot_size*loss_per_lot
            dollar_reward=lot_size*max(abs(tp-p)-BTC_SPREAD_USD,0)*BTC_CONTRACT_BTC_PER_LOT
    return locals()
def scalp_analysis(c5,c15,forex=False):
    s5=snap(c5);s15=snap(c15)
    if not all((s5,s15)):return None
    c=s5["c"];p=s5["p"];a=atr(c);r=s5["r"];t5,t15=trend(s5),trend(s15);st=structure(c);lb,ls=liquidity(c);recent=c[-30:];sup=min(float(x[1]) for x in recent);res=max(float(x[2]) for x in recent);buy=sell=0;why=[];buy_conf=sell_conf=0
    if t5=="UP":buy+=30;buy_conf+=1
    elif t5=="DOWN":sell+=30;sell_conf+=1
    if t15=="UP":buy+=30;buy_conf+=1
    elif t15=="DOWN":sell+=30;sell_conf+=1
    if st=="UP":buy+=15;buy_conf+=1;why.append("هيكل 5m صاعد")
    elif st=="DOWN":sell+=15;sell_conf+=1;why.append("هيكل 5m هابط")
    if lb:buy+=15;buy_conf+=1;why.append("Liquidity sweep BUY")
    if ls:sell+=15;sell_conf+=1;why.append("Liquidity sweep SELL")
    if r>=55:buy+=10;buy_conf+=1
    elif r<=45:sell+=10;sell_conf+=1
    raw_total=max(buy+sell,1);raw_bp=round(100*buy/raw_total);raw_sp=100-raw_bp
    if forex:
        # EUR/USD: confidence is deliberately capped unless several independent confirmations agree.
        bp=min(raw_bp,95 if buy_conf>=4 else 85 if buy_conf>=3 else 70 if buy_conf>=2 else 55)
        sp=min(raw_sp,95 if sell_conf>=4 else 85 if sell_conf>=3 else 70 if sell_conf>=2 else 55)
        side="LONG" if buy_conf>=3 and t5=="UP" and t15=="UP" and bp>=75 and buy>=sell+18 else "SHORT" if sell_conf>=3 and t5=="DOWN" and t15=="DOWN" and sp>=75 and sell>=buy+18 else "WAIT"
        if side=="WAIT" and max(buy_conf,sell_conf)<3:why.append("أقل من 3 تأكيدات — لا دخول")
    else:
        bp=raw_bp;sp=raw_sp;side="LONG" if bp>=68 and buy>=sell+18 else "SHORT" if sp>=68 and sell>=buy+18 else "WAIT"
    if side=="LONG" and res-p<1.15*a:side="WAIT";why.append("مقاومة قريبة — منع مطاردة")
    if side=="SHORT" and p-sup<1.15*a:side="WAIT";why.append("دعم قريب — منع مطاردة")
    ranges=[float(x[2])-float(x[1]) for x in c[-15:-1]];spike=(float(c[-1][2])-float(c[-1][1]))>max(sum(ranges)/len(ranges)*2.5,a*2)
    if spike:side="WAIT";why.append("تقلب غير طبيعي")
    risk=max(a*1.5,p*(.0008 if forex else .003));sl=p-risk if side=="LONG" else p+risk if side=="SHORT" else None;tp=p+risk*2 if side=="LONG" else p-risk*2 if side=="SHORT" else None
    return locals()
def analyze_eur():return scalp_analysis(eur_candles("5m",120),eur_candles("15m",120),True)
def analyze_jpy():return scalp_analysis(jpy_candles("5m",120),jpy_candles("15m",120),True)

paper={}
def restore_paper(symbol,env_name):
    raw=os.getenv(env_name,"").strip()
    if not raw:return
    try:
        parts=[p.strip() for p in raw.split(",")]
        side=parts[0].upper();entry=float(parts[1]);sl=float(parts[2]);tp=float(parts[3])
        if side not in ("LONG","SHORT"):raise ValueError("invalid side")
        q={"side":side,"entry":entry,"sl":sl,"tp":tp,"opened_at":time.time(),"opened_bar":0,"last_bar":0,"restored":True}
        if symbol=="BTC/USD":
            lot=float(parts[4]) if len(parts)>4 else 0.0
            q.update({"lot_size":lot,"planned_risk":0.0,"planned_reward":0.0})
        paper[symbol]=q
        print(f'PAPER RESTORED {symbol} {side} entry={entry:.6f} sl={sl:.6f} tp={tp:.6f}')
    except Exception as e:print(f"PAPER RESTORE ERROR {symbol}",e)
restore_paper("BTC/USD","PAPER_RESTORE_BTCUSD")
restore_paper("EUR/USD","PAPER_RESTORE_EURUSD")
restore_paper("USD/JPY","PAPER_RESTORE_USDJPY")
def paper_track(symbol,x):
    if not PAPER_MODE or symbol not in paper or not x:return
    q=paper[symbol];bar=int(x["c"][-1][0])
    if bar<=q["opened_bar"] or bar<=q.get("last_bar",0):return
    q["last_bar"]=bar;hi=float(x["c"][-1][2]);lo=float(x["c"][-1][1])
    stop=lo<=q["sl"] if q["side"]=="LONG" else hi>=q["sl"]
    target=hi>=q["tp"] if q["side"]=="LONG" else lo<=q["tp"]
    if not (stop or target):return
    result="SL_AMBIGUOUS" if stop and target else "TP" if target else "SL";exit_price=q["sl"] if stop else q["tp"];delta=(exit_price-q["entry"]) if q["side"]=="LONG" else (q["entry"]-exit_price)
    financial=""
    if symbol=="BTC/USD":
        quantity=q.get("lot_size",0.0)*BTC_CONTRACT_BTC_PER_LOT
        net_pnl=(delta-BTC_SPREAD_USD)*quantity
        financial=f'\n📦 الحجم: {q.get("lot_size",0.0):.2f} lot\n💵 الصافي بعد السبريد: ${net_pnl:+.2f}'
    print(f'PAPER CLOSE {symbol} {result} entry={q["entry"]:.6f} exit={exit_price:.6f} delta={delta:.6f}{financial}')
    send(f'🧪 نتيجة صفقة تجريبية — {symbol} — لا تدخل بأموال حقيقية\n🎯 النتيجة: {result}\n📍 Entry: {q["entry"]:.6f}\n🚪 Exit: {exit_price:.6f}\n📊 الحركة: {delta:.6f}'+financial)
    del paper[symbol]
def paper_open(symbol,x,message):
    if time.time()-STARTED_AT<STARTUP_BLOCK_SECONDS:
        remaining=max(0,int(STARTUP_BLOCK_SECONDS-(time.time()-STARTED_AT)))
        print(f"SIGNAL BLOCKED {symbol}: startup duplicate-protection window remaining={remaining}s")
        return False
    if not PAPER_MODE or not x or x["side"] not in ("LONG","SHORT") or symbol in paper:return False
    q={"side":x["side"],"entry":x["p"],"sl":x["sl"],"tp":x["tp"],"opened_at":time.time(),"opened_bar":int(x["c"][-1][0]),"last_bar":0}
    if symbol=="BTC/USD":q.update({"lot_size":x.get("lot_size",0.0),"planned_risk":x.get("dollar_risk",0.0),"planned_reward":x.get("dollar_reward",0.0)})
    paper[symbol]=q
    print(f'PAPER OPEN {symbol} {q["side"]} entry={q["entry"]:.6f} sl={q["sl"]:.6f} tp={q["tp"]:.6f}')
    send("🧪 صفقة تجريبية — لا تدخل بأموال حقيقية\n\n"+message);return True

def ar(x):return {"LONG":"🟢 شراء","SHORT":"🔴 بيع","WAIT":"🟡 انتظار","UP":"صاعد","DOWN":"هابط","MIXED":"مختلط","RANGE":"عرضي","POSITIVE":"إيجابي","NEGATIVE":"سلبي","NEUTRAL":"محايد"}.get(x,x)
def msg(x):
    risk="لا دخول مؤكد" if x["side"]=="WAIT" else f'🛑 SL: ${x["sl"]:.2f}\n🎯 TP: ${x["tp"]:.2f}\n📦 الحجم المحسوب: {x["lot_size"]:.2f} lot\n💵 مخاطرة الصفقة: ${x["dollar_risk"]:.2f} من ${BTC_ACCOUNT_BALANCE:.2f} ({BTC_RISK_PCT:.2f}%)\n💰 العائد المتوقع بعد السبريد: ${x["dollar_reward"]:.2f}'
    return f'₿ BTC ANALYST PRO\n\n🎯 القرار: {ar(x["side"])}\n💰 ${x["p"]:.2f}\n🟢 ميل الشراء: {x["bp"]}% | 🔴 ميل البيع: {x["sp"]}%\n📐 الهيكل 15m: {ar(x["st"])}\n⏱ 15m/1h/4h: {ar(x["t15"])} / {ar(x["t1"])} / {ar(x["t4"])}\n💧 Liquidity: {"Sweep BUY" if x["lb"] else "Sweep SELL" if x["ls"] else "لا Sweep مؤكد"}\n📈 RSI: {x["r"]:.1f} | ATR: {x["a"]:.2f}\n🟢 دعم: ${x["sup"]:.0f} | 🔴 مقاومة: ${x["res"]:.0f}\n📰 أخبار: {ar(x["n"])} | Reddit: {ar(x["rd"])} — معلومات فقط\n{risk}\n🧠 {"؛ ".join(x["why"][:5]) if x["why"] else "توافق محدود"}\n\n⚠️ إشارة تحليلية فقط.'
def scalp_msg(x,name,price_digits=3):
    f=lambda v:f'{v:.{price_digits}f}';risk="لا دخول مؤكد" if x["side"]=="WAIT" else f'🛑 SL: {f(x["sl"])}\n🎯 TP: {f(x["tp"])}'
    return f'{name}\n\n🎯 القرار: {ar(x["side"])}\n💰 السعر: {f(x["p"])}\n🟢 ميل الشراء: {x["bp"]}% | 🔴 ميل البيع: {x["sp"]}%\n⏱ 5m/15m: {ar(x["t5"])} / {ar(x["t15"])}\n📐 الهيكل 5m: {ar(x["st"])}\n💧 Liquidity: {"Sweep BUY" if x["lb"] else "Sweep SELL" if x["ls"] else "لا Sweep مؤكد"}\n📈 RSI 5m: {x["r"]:.1f} | ATR: {f(x["a"])}\n🟢 دعم: {f(x["sup"])} | 🔴 مقاومة: {f(x["res"])}\n{risk}\n🧠 {"؛ ".join(x["why"][:5]) if x["why"] else "توافق محدود"}\n\n⚠️ إشارة تحليلية فقط وليست ضمان ربح.'
last=None;last_eur=None;last_jpy=None;last_report=0;last_eur_report=0;last_jpy_report=0
while True:
    print("LOOP START")
    now=time.time()
    x=run_with_timeout(analyze,20,"BTC analyze")
    e=run_with_timeout(analyze_eur,25,"EURUSD analyze")
    j=run_with_timeout(analyze_jpy,25,"USDJPY analyze")
    print("HEARTBEAT")
    if x:
        print(f'BTC {x["p"]:.2f} {x["side"]} BUY={x["bp"]}% SELL={x["sp"]}%');periodic=last_report==0 or now-last_report>=REPORT;immediate=x["side"] in ("LONG","SHORT") and x["side"]!=last
        if PAPER_MODE:
            paper_track("BTC/USD",x);
            if immediate:paper_open("BTC/USD",x,msg(x))
        elif periodic or immediate:send(msg(x))
        if periodic:last_report=now
        last=x["side"]
    if e:
        print(f'EURUSD {e["p"]:.5f} {e["side"]} BUY={e["bp"]}% SELL={e["sp"]}%');periodic=last_eur_report==0 or now-last_eur_report>=REPORT;immediate=e["side"] in ("LONG","SHORT") and e["side"]!=last_eur
        if PAPER_MODE:
            paper_track("EUR/USD",e);
            if immediate:paper_open("EUR/USD",e,scalp_msg(e,"💶 EUR/USD SCALP MONITOR",5))
        elif periodic or immediate:send(scalp_msg(e,"💶 EUR/USD SCALP MONITOR",5))
        if periodic:last_eur_report=now
        last_eur=e["side"]
    if j:
        print(f'USDJPY {j["p"]:.3f} {j["side"]} BUY={j["bp"]}% SELL={j["sp"]}%');periodic=last_jpy_report==0 or now-last_jpy_report>=REPORT;immediate=j["side"] in ("LONG","SHORT") and j["side"]!=last_jpy
        if PAPER_MODE:
            paper_track("USD/JPY",j);
            if immediate:paper_open("USD/JPY",j,scalp_msg(j,"💴 USD/JPY SCALP MONITOR",3))
        elif periodic or immediate:send(scalp_msg(j,"💴 USD/JPY SCALP MONITOR",3))
        if periodic:last_jpy_report=now
        last_jpy=j["side"]
    time.sleep(60)
