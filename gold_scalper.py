import os,time,requests,json
TOKEN=os.getenv("GOLD_TELEGRAM_BOT_TOKEN");CHAT=os.getenv("GOLD_TELEGRAM_CHAT_ID");KEY=os.getenv("TWELVE_DATA_API_KEY")
URL="https://api.twelvedata.com/time_series";REPORT=900;cache={};TTL={"5min":60,"15min":180,"1h":600}
def send(m):
    if not TOKEN or not CHAT:return
    try:requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",data={"chat_id":CHAT,"text":m},timeout=15).raise_for_status()
    except Exception as e:print("Telegram",e)
def fetch(sym,tf,n=200):
    k=f"{sym}:{tf}:{n}";now=time.time()
    if k in cache and now-cache[k][0]<TTL.get(tf,120):return cache[k][1]
    try:
        r=requests.get(URL,params={"symbol":sym,"interval":tf,"outputsize":n,"apikey":KEY,"format":"JSON"},timeout=30);r.raise_for_status();d=r.json()
        if d.get("status")=="error":print("TD",d.get("message"));return None
        x=[]
        for z in reversed(d.get("values",[])):
            try:x.append({"t":z.get("datetime"),"o":float(z["open"]),"h":float(z["high"]),"l":float(z["low"]),"c":float(z["close"])})
            except:pass
        if x:cache[k]=(now,x)
        return x or None
    except Exception as e:print("Data",e);return None
def ema(v,p):
    k=2/(p+1);x=v[0]
    for z in v[1:]:x=z*k+x*(1-k)
    return x
def rsi(v,p=14):
    d=[v[i]-v[i-1] for i in range(1,len(v))];g=sum(max(x,0) for x in d[-p:])/p;l=sum(max(-x,0) for x in d[-p:])/p
    return 100 if l==0 else 100-100/(1+g/l)
def atr(c,p=14):
    t=[]
    for i in range(1,len(c)):t.append(max(c[i]["h"]-c[i]["l"],abs(c[i]["h"]-c[i-1]["c"]),abs(c[i]["l"]-c[i-1]["c"])))
    return sum(t[-p:])/p
def snap(c):
    if not c or len(c)<65:return None
    c=c[:-1];v=[x["c"] for x in c];return {"p":v[-1],"e9":ema(v[-50:],9),"e20":ema(v[-60:],20),"e50":ema(v[-65:],50),"r":rsi(v),"a":atr(c),"c":c}
def trend(s):
    if s["p"]>s["e9"]>s["e20"]>s["e50"]:return "UP"
    if s["p"]<s["e9"]<s["e20"]<s["e50"]:return "DOWN"
    return "MIXED"
def pivots(c,L=2,R=2):
    q=[]
    for i in range(L,len(c)-R):
        if c[i]["h"]==max(x["h"] for x in c[i-L:i+R+1]):q.append((i,c[i]["h"],"H"))
        if c[i]["l"]==min(x["l"] for x in c[i-L:i+R+1]):q.append((i,c[i]["l"],"L"))
    q.sort();out=[]
    for p in q:
        if out and out[-1][2]==p[2]:
            if (p[2]=="H" and p[1]>out[-1][1]) or (p[2]=="L" and p[1]<out[-1][1]):out[-1]=p
        else:out.append(p)
    return out
def structure(c):
    ps=pivots(c[-100:]);hs=[x for x in ps if x[2]=="H"][-2:];ls=[x for x in ps if x[2]=="L"][-2:]
    if len(hs)==2 and len(ls)==2:
        if hs[-1][1]>hs[-2][1] and ls[-1][1]>ls[-2][1]:return "BULLISH"
        if hs[-1][1]<hs[-2][1] and ls[-1][1]<ls[-2][1]:return "BEARISH"
    return "RANGE"
def levels(c):
    ps=pivots(c[-120:]);p=c[-1]["c"];lows=sorted([x[1] for x in ps if x[2]=="L" and x[1]<=p],reverse=True);highs=sorted([x[1] for x in ps if x[2]=="H" and x[1]>=p])
    return (lows[0] if lows else min(x["l"] for x in c[-30:])),(highs[0] if highs else max(x["h"] for x in c[-30:]))
def liquidity(c,a):
    prev=c[-25:-1];last=c[-1];hs=sorted([x[1] for x in pivots(prev,2,2) if x[2]=="H"]);ls=sorted([x[1] for x in pivots(prev,2,2) if x[2]=="L"])
    buy=sell=False;desc=[]
    if hs:
        h=hs[-1]
        if last["h"]>h and last["c"]<h:sell=True;desc.append("سحب سيولة فوق قمة ثم إغلاق تحتها")
    if ls:
        l=ls[0]
        if last["l"]<l and last["c"]>l:buy=True;desc.append("سحب سيولة تحت قاع ثم إغلاق فوقه")
    tol=max(a*.18,last["c"]*.00012);eqh=any(abs(hs[i]-hs[i-1])<=tol for i in range(1,len(hs)));eql=any(abs(ls[i]-ls[i-1])<=tol for i in range(1,len(ls)))
    return {"buy":buy,"sell":sell,"eqh":eqh,"eql":eql,"text":desc}
def price_action(c):
    x=c[-1];prev=c[-2];body=abs(x["c"]-x["o"]);rng=max(x["h"]-x["l"],1e-9);bull=x["c"]>x["o"] and x["c"]>prev["h"];bear=x["c"]<x["o"] and x["c"]<prev["l"]
    pinbull=(min(x["o"],x["c"])-x["l"])>body*2 and body/rng<.45;pinbear=(x["h"]-max(x["o"],x["c"]))>body*2 and body/rng<.45
    return "BULLISH" if bull or pinbull else "BEARISH" if bear or pinbear else "NEUTRAL"
def breakout(c,sup,res,a):
    x=c[-1];p=c[-2];buf=a*.08
    if x["c"]>res+buf:return "BULL_BREAK"
    if x["c"]<sup-buf:return "BEAR_BREAK"
    if p["c"]>res and x["l"]<=res+buf and x["c"]>res:return "BULL_RETEST"
    if p["c"]<sup and x["h"]>=sup-buf and x["c"]<sup:return "BEAR_RETEST"
    return "NONE"
def near(x,t,tol=.12):return t*(1-tol)<=x<=t*(1+tol)
def harmonic(c):
    ps=pivots(c[-130:],3,3);best=None
    for q in range(max(0,len(ps)-12),max(0,len(ps)-4)):
        P=ps[q:q+5]
        if len(P)<5:continue
        X,A,B,C,D=[x[1] for x in P];XA=abs(A-X);AB=abs(B-A);BC=abs(C-B);CD=abs(D-C);AD=abs(D-A)
        if min(XA,AB,BC,CD)==0:continue
        ab,bc,cd,ad=AB/XA,BC/AB,CD/BC,AD/XA;name=None
        if near(ab,.618,.10) and .382<=bc<=.886 and 1.13<=cd<=1.75 and near(ad,.786,.12):name="Gartley"
        elif .382<=ab<=.50 and .382<=bc<=.886 and 1.5<=cd<=2.7 and near(ad,.886,.12):name="Bat"
        elif near(ab,.786,.12) and .382<=bc<=.886 and 1.5<=cd<=2.7 and 1.15<=ad<=1.40:name="Butterfly"
        elif .382<=ab<=.618 and .382<=bc<=.886 and 2<=cd<=3.8 and 1.45<=ad<=1.75:name="Crab"
        elif .70<=AB/CD<=1.30 and .45<=bc<=.90:name="ABCD"
        if name:best={"name":name,"side":"BUY" if P[-1][2]=="L" else "SELL"}
    return best
def analyze():
    s5=snap(fetch("XAU/USD","5min"));s15=snap(fetch("XAU/USD","15min"));s1=snap(fetch("XAU/USD","1h"))
    if not all((s5,s15,s1)):return None
    p=s5["p"];a=s5["a"];sup,res=levels(s5["c"]);st5=structure(s5["c"]);st15=structure(s15["c"]);liq=liquidity(s5["c"],a);pa=price_action(s5["c"]);br=breakout(s5["c"],sup,res,a);h5=harmonic(s5["c"]);h15=harmonic(s15["c"]);buy=sell=0;why=[]
    t5,t15,t1=trend(s5),trend(s15),trend(s1)
    if t5=="UP":buy+=14
    elif t5=="DOWN":sell+=14
    if t15=="UP":buy+=16
    elif t15=="DOWN":sell+=16
    if t1=="UP":buy+=5
    elif t1=="DOWN":sell+=5
    if st5=="BULLISH":buy+=14;why.append("هيكل 5m صاعد")
    elif st5=="BEARISH":sell+=14;why.append("هيكل 5m هابط")
    if st15=="BULLISH":buy+=10
    elif st15=="BEARISH":sell+=10
    if liq["buy"]:buy+=20;why+=liq["text"]
    if liq["sell"]:sell+=20;why+=liq["text"]
    if liq["eql"]:buy+=4;why.append("قيعان متساوية/سيولة محتملة أسفل السعر")
    if liq["eqh"]:sell+=4;why.append("قمم متساوية/سيولة محتملة أعلى السعر")
    if pa=="BULLISH":buy+=12;why.append("Price Action صاعد")
    elif pa=="BEARISH":sell+=12;why.append("Price Action هابط")
    if br in ("BULL_BREAK","BULL_RETEST"):buy+=18;why.append("كسر/إعادة اختبار صاعد")
    elif br in ("BEAR_BREAK","BEAR_RETEST"):sell+=18;why.append("كسر/إعادة اختبار هابط")
    if h5:buy+=18 if h5["side"]=="BUY" else 0;sell+=18 if h5["side"]=="SELL" else 0;why.append(f'Harmonic 5m {h5["name"]} {h5["side"]}')
    if h15:buy+=12 if h15["side"]=="BUY" else 0;sell+=12 if h15["side"]=="SELL" else 0;why.append(f'Harmonic 15m {h15["name"]} {h15["side"]}')
    if s5["r"]<35:buy+=7
    elif s5["r"]>65:sell+=7
    total=max(buy+sell,1);bp=round(100*buy/total);sp=100-bp;side="BUY" if bp>=65 and buy>=sell+18 else "SELL" if sp>=65 and sell>=buy+18 else "WAIT"
    ranges=[x["h"]-x["l"] for x in s5["c"][-15:-1]];spike=(s5["c"][-1]["h"]-s5["c"][-1]["l"])>max(sum(ranges)/len(ranges)*2.5,a*2)
    if spike:side="WAIT";why.append("تقلب غير طبيعي — حماية الدخول")
    sl=p-1.15*a if side=="BUY" else p+1.15*a if side=="SELL" else None;tp1=p+1.1*a if side=="BUY" else p-1.1*a if side=="SELL" else None;tp2=p+1.7*a if side=="BUY" else p-1.7*a if side=="SELL" else None;tp3=p+2.4*a if side=="BUY" else p-2.4*a if side=="SELL" else None
    return locals()
def ar(x):return {"BUY":"🟢 شراء","SELL":"🔴 بيع","WAIT":"🟡 انتظار","UP":"صاعد","DOWN":"هابط","MIXED":"مختلط","BULLISH":"صاعد","BEARISH":"هابط","RANGE":"عرضي","NEUTRAL":"محايد"}.get(x,x)
def msg(x):
    risk="لا دخول مؤكد حاليًا" if x["side"]=="WAIT" else f'📍 Entry: {x["p"]:.2f}\n🛑 SL: {x["sl"]:.2f}\n🎯 TP1: {x["tp1"]:.2f}\n🎯 TP2: {x["tp2"]:.2f}\n🎯 TP3: {x["tp3"]:.2f}'
    h5=x["h5"]["name"]+" "+ar(x["h5"]["side"]) if x["h5"] else "لا يوجد";h15=x["h15"]["name"]+" "+ar(x["h15"]["side"]) if x["h15"] else "لا يوجد"
    return f'🥇 GOLD SCALPER PRO\n\n🎯 القرار: {ar(x["side"])}\n💰 XAU/USD: {x["p"]:.2f}\n🟢 ميل الشراء: {x["bp"]}% | 🔴 ميل البيع: {x["sp"]}%\n\n📐 كلاسيكي 5m: {ar(x["st5"])} | 15m: {ar(x["st15"])}\n📊 EMA 5m/15m/1h: {ar(x["t5"])} / {ar(x["t15"])} / {ar(x["t1"])}\n🕯 Price Action: {ar(x["pa"])}\n💧 Liquidity: {"Sweep BUY" if x["liq"]["buy"] else "Sweep SELL" if x["liq"]["sell"] else "لا Sweep مؤكد"}\n🟢 دعم: {x["sup"]:.2f} | 🔴 مقاومة: {x["res"]:.2f}\n🧬 Harmonic 5m: {h5}\n🧬 Harmonic 15m: {h15}\n📈 RSI: {x["s5"]["r"]:.1f} | ATR: {x["a"]:.2f}\n\n{risk}\n🧠 التوافق: {"؛ ".join(x["why"][:7]) if x["why"] else "توافق ضعيف"}\n\n⚠️ تحليل احتمالي فقط — لا توجد صفقة منفذة.'
STATE_FILE=os.getenv("GOLD_STATE_FILE","gold_signal_state.json")
def load_state():
    try:
        with open(STATE_FILE,"r",encoding="utf-8") as f:
            d=json.load(f)
            return d if isinstance(d,dict) else {"active":[],"history":[],"next_id":1}
    except Exception:
        return {"active":[],"history":[],"next_id":1}
def save_state():
    try:
        tmp=STATE_FILE+".tmp"
        with open(tmp,"w",encoding="utf-8") as f:json.dump(state,f,ensure_ascii=False)
        os.replace(tmp,STATE_FILE)
    except Exception as e:print("State",e)
def stats_text():
    h=state["history"];closed=len(h)
    if not closed:return "📊 لا توجد نتائج مغلقة بعد"
    wins=sum(1 for z in h if z.get("max_tp",0)>=1);tp3=sum(1 for z in h if z.get("max_tp",0)>=3)
    return f"📊 النتائج: {closed} | نجاح TP1: {wins} ({wins/closed*100:.1f}%) | TP3: {tp3}"
def open_signal(x):
    sig={"id":state["next_id"],"side":x["side"],"entry":x["p"],"sl":x["sl"],"tps":[x["tp1"],x["tp2"],x["tp3"]],"hit":[False,False,False],"max_tp":0,"opened_candle":x["s5"]["c"][-1].get("t"),"opened_at":time.time()}
    state["next_id"]+=1;state["active"].append(sig);save_state()
    print(f'Signal #{sig["id"]} opened {sig["side"]} @ {sig["entry"]:.2f}')
def close_signal(sig,result,price):
    sig["result"]=result;sig["closed_at"]=time.time();sig["exit_price"]=price
    state["history"].append(sig.copy());state["history"]=state["history"][-500:]
    if sig in state["active"]:state["active"].remove(sig)
    save_state()
def track_signals(x):
    if not state["active"]:return
    candle=x["s5"]["c"][-1];hi,lo=candle["h"],candle["l"];changed=False
    for sig in list(state["active"]):
        if candle.get("t")==sig.get("opened_candle"):continue
        side=sig["side"];target_touch=(lambda level: hi>=level) if side=="BUY" else (lambda level: lo<=level)
        for i,target in enumerate(sig["tps"]):
            if not sig["hit"][i] and target_touch(target):
                sig["hit"][i]=True;sig["max_tp"]=max(sig["max_tp"],i+1);changed=True
                icon="🏆" if i==2 else "✅"
                send(f'{icon} GOLD SIGNAL #{sig["id"]} — TP{i+1} HIT\n🎯 الهدف: {target:.2f}\n📈 أعلى الشمعة: {hi:.2f} | 📉 أدناها: {lo:.2f}')
        if sig["hit"][2]:
            close_signal(sig,"TP3",sig["tps"][2])
            send(f'🏁 GOLD SIGNAL #{sig["id"]} اكتملت بنجاح — TP3\n{stats_text()}');continue
        stop_hit=lo<=sig["sl"] if side=="BUY" else hi>=sig["sl"]
        if stop_hit:
            result="SL_AFTER_TP"+str(sig["max_tp"]) if sig["max_tp"] else "SL"
            close_signal(sig,result,sig["sl"])
            send(f'❌ GOLD SIGNAL #{sig["id"]} — SL HIT\n🛑 الوقف: {sig["sl"]:.2f}\n🎯 أعلى هدف تحقق: TP{sig["max_tp"] if sig["max_tp"] else 0}\n{stats_text()}');continue
    if changed:save_state()
state=load_state()
last=None;last_report=0
while True:
    x=analyze()
    if x:
        now=time.time();print(f'XAU {x["p"]:.2f} {x["side"]} BUY={x["bp"]}% SELL={x["sp"]}%')
        periodic=last_report==0 or now-last_report>=REPORT;immediate=x["side"] in ("BUY","SELL") and x["side"]!=last
        track_signals(x)
        if periodic or immediate:
            send(msg(x));last_report=now if periodic else last_report
            if immediate:open_signal(x)
        last=x["side"]
    time.sleep(30)
