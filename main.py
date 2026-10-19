import os,time,re,math,xml.etree.ElementTree as ET,requests
from requests.adapters import HTTPAdapter
from paper_ledger import Ledger, new_position
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN");CHAT=os.getenv("TELEGRAM_CHAT_ID");REPORT=900
PAPER_MODE=os.getenv("CRYPTO_PAPER_MODE","true").strip().lower() not in ("0","false","off","no")
STARTED_AT=time.time()
STARTUP_BLOCK_SECONDS=float(os.getenv("PAPER_STARTUP_BLOCK_SECONDS","0"))
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
def candles(g,n,product="BTC-USD"):
    try:
        r=SESSION.get(f"https://api.exchange.coinbase.com/products/{product}/candles",params={"granularity":g},timeout=(5,10),headers={"User-Agent":"ia-crypto-bot/2.0"});r.raise_for_status();x=r.json();x.sort(key=lambda z:z[0]);return x[-n:]
    except Exception as e:print("Coinbase",e);return None
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
def analyze(product="BTC-USD"):
    c15=candles(900,100,product);c1=candles(3600,300,product);c4=build4(c1);s15=snap(c15);s1=snap(c1);s4=snap(c4)
    if not all((s15,s1,s4)):return None
    if time.time()-(s15["c"][-1][0]+900)>900:
        print(f"STALE DATA {product}: no new entries");return None
    spread=BTC_SPREAD_USD if product=="BTC-USD" else env_float("ETH_SPREAD_USD",2.0)
    contract=BTC_CONTRACT_BTC_PER_LOT if product=="BTC-USD" else 1.0
    lot_step=BTC_LOT_STEP if product=="BTC-USD" else 0.01
    min_lot=BTC_MIN_LOT if product=="BTC-USD" else 0.01
    max_lot=BTC_MAX_LOT if product=="BTC-USD" else 100.0
    c=s15["c"];p=s15["p"];a=atr(c);r=s15["r"];t15,t1,t4=trend(s15),trend(s1),trend(s4);st=structure(c);lb,ls=liquidity(c);vol=[float(x[5]) for x in c];vr=vol[-1]/(sum(vol[-21:-1])/20 or 1);recent=c[-20:];sup=min(float(x[1]) for x in recent);res=max(float(x[2]) for x in recent);n="NOT_USED";rd="NOT_USED";buy=sell=0;why=[]
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
        loss_per_lot=(abs(p-sl)+spread)*contract
        raw_lot=risk_budget/loss_per_lot if loss_per_lot>0 else 0.0
        lot_size=math.floor(raw_lot/lot_step+1e-12)*lot_step if lot_step>0 else 0.0
        lot_size=min(lot_size,max_lot)
        if lot_size<min_lot:
            side="WAIT";lot_size=0.0;why.append("حجم العقد الأدنى يتجاوز حد المخاطرة — لا دخول")
        else:
            dollar_risk=lot_size*loss_per_lot
            dollar_reward=lot_size*max(abs(tp-p)-spread,0)*contract
    return locals()
# A disabled symbol is never fetched, restored, opened, or sent as a signal.
ACTIVE_SYMBOLS=("BTC/USD","ETH/USD")
PAPER_MODE=True  # This release is authorized for simulation only.
if os.getenv("RAILWAY_PROJECT_ID") and not os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
    raise RuntimeError("A persistent volume is required before paper signals can start")
LEDGER=Ledger(os.getenv("PAPER_DB_PATH","/data/crypto-paper.sqlite3"))
paper=LEDGER.positions()
if any(symbol not in ACTIVE_SYMBOLS for symbol in paper):
    raise RuntimeError("Disabled position requires explicit archival before starting")

def paper_track(symbol,x):
    if symbol not in paper or not x:return
    q=paper[symbol]
    # Replay every unseen closed 15m candle, including those missed during a restart.
    bars=[z for z in x["c"] if int(z[0])>q["last_bar"]]
    for z in bars:
        bar=int(z[0])
        if bar!=q["last_bar"]+900:
            if not q.get("data_gap"):
                q["data_gap"]=True;LEDGER.save(symbol,q)
                LEDGER.note("DATA_GAP",symbol,{"after":q["last_bar"],"next":bar})
                print(f"DATA GAP {symbol}: position quarantined pending reconciliation")
            return
        hi=float(z[2]);lo=float(z[1])
        stop=lo<=q["sl"] if q["side"]=="LONG" else hi>=q["sl"]
        target=hi>=q["tp"] if q["side"]=="LONG" else lo<=q["tp"]
        if stop or target:
            result="SL_AMBIGUOUS" if stop and target else "SL" if stop else "TP"
            event=LEDGER.close(symbol,q,result,q["sl"] if stop else q["tp"],bar)
            del paper[symbol]
            print(f'PAPER CLOSE {symbol} {result} net={event["net_pnl"]:+.2f} id={q["id"]}')
            send(f'🧪 نتيجة تجريبية — {symbol}\n{result}\nالصافي بعد السبريد: ${event["net_pnl"]:+.2f}\nID: {q["id"]}')
            return
        q["last_bar"]=bar
        q.pop("data_gap",None)
        LEDGER.save(symbol,q)

def paper_open(symbol,x,message):
    if symbol not in ACTIVE_SYMBOLS or not x or x["side"] not in ("LONG","SHORT") or symbol in paper:return False
    if time.time()-STARTED_AT<STARTUP_BLOCK_SECONDS:return False
    # Shared risk budget: adding ETH must not double the existing account risk.
    used=sum(q["planned_risk"] for q in paper.values())
    if used+x["dollar_risk"]>BTC_ACCOUNT_BALANCE*BTC_RISK_PCT/100+1e-6:
        print(f"SIGNAL BLOCKED {symbol}: shared risk budget");return False
    q=new_position(x)
    LEDGER.save(symbol,q,opening=True);paper[symbol]=q
    print(f'PAPER OPEN {symbol} {q["side"]} entry={q["entry"]:.6f} id={q["id"]}')
    send("🧪 صفقة تجريبية — لا تدخل بأموال حقيقية\n\n"+message)
    return True

def ar(x):return {"LONG":"🟢 شراء","SHORT":"🔴 بيع","WAIT":"🟡 انتظار","UP":"صاعد","DOWN":"هابط","MIXED":"مختلط","RANGE":"عرضي","POSITIVE":"إيجابي","NEGATIVE":"سلبي","NEUTRAL":"محايد"}.get(x,x)
def msg(x,symbol="BTC/USD"):
    risk="لا دخول مؤكد" if x["side"]=="WAIT" else f'🛑 SL: ${x["sl"]:.2f}\n🎯 TP: ${x["tp"]:.2f}\n📦 الحجم المحسوب: {x["lot_size"]:.2f} lot\n💵 مخاطرة الصفقة: ${x["dollar_risk"]:.2f} من ${BTC_ACCOUNT_BALANCE:.2f} ({BTC_RISK_PCT:.2f}%)\n💰 العائد المتوقع بعد السبريد: ${x["dollar_reward"]:.2f}'
    return f'{symbol} ANALYST PRO\n\n🎯 القرار: {ar(x["side"])}\n💰 ${x["p"]:.2f}\n🟢 ميل الشراء: {x["bp"]}% | 🔴 ميل البيع: {x["sp"]}%\n📐 الهيكل 15m: {ar(x["st"])}\n⏱ 15m/1h/4h: {ar(x["t15"])} / {ar(x["t1"])} / {ar(x["t4"])}\n💧 Liquidity: {"Sweep BUY" if x["lb"] else "Sweep SELL" if x["ls"] else "لا Sweep مؤكد"}\n📈 RSI: {x["r"]:.1f} | ATR: {x["a"]:.2f}\n🟢 دعم: ${x["sup"]:.0f} | 🔴 مقاومة: ${x["res"]:.0f}\n📰 أخبار: {ar(x["n"])} | Reddit: {ar(x["rd"])} — معلومات فقط\n{risk}\n🧠 {"؛ ".join(x["why"][:5]) if x["why"] else "توافق محدود"}\n\n⚠️ إشارة تحليلية فقط.'
def main():
    print("PAPER ONLY active=BTC/USD,ETH/USD disabled=EUR/USD,USD/JPY")
    print(f"LEDGER READY restored={len(paper)} path={os.getenv('PAPER_DB_PATH','/data/crypto-paper.sqlite3')}")
    print("LEGACY BTC: 23 closed trades preserved under evaluation/; unresolved historical positions remain archived")
    while True:
        for symbol,product in (("BTC/USD","BTC-USD"),("ETH/USD","ETH-USD")):
            x=run_with_timeout(lambda product=product:analyze(product),40,symbol)
            if not x:continue
            print(f'{symbol} {x["p"]:.2f} {x["side"]} BUY={x["bp"]}% SELL={x["sp"]}%')
            paper_track(symbol,x)
            if LEDGER.observe_signal(symbol,x["side"],int(x["c"][-1][0])):
                paper_open(symbol,x,msg(x,symbol))
        print("HEARTBEAT")
        time.sleep(60)

if __name__=="__main__":main()
