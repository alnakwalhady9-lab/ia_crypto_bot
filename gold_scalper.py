import os
import time
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
REPORT_SECONDS = 900


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing"); return
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",data={"chat_id":TELEGRAM_CHAT_ID,"text":message},timeout=10)
        r.raise_for_status(); print("Telegram message sent")
    except requests.RequestException as e: print(f"Telegram error: {e}")


def ema(values,period):
    k=2/(period+1); result=values[0]
    for value in values[1:]: result=value*k+result*(1-k)
    return result


def rsi(values,period=14):
    if len(values)<=period:return None
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    gains=[max(x,0) for x in changes[-period:]]; losses=[max(-x,0) for x in changes[-period:]]
    ag=sum(gains)/period; al=sum(losses)/period
    return 100.0 if al==0 else 100-(100/(1+ag/al))


def atr(candles,period=14):
    if len(candles)<=period:return None
    tr=[]
    for i in range(1,len(candles)):
        h,l,pc=candles[i]["high"],candles[i]["low"],candles[i-1]["close"]
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(tr[-period:])/period


def get_candles(interval):
    if not TWELVE_DATA_API_KEY:
        print("TWELVE_DATA_API_KEY is missing"); return None
    params={"symbol":"XAU/USD","interval":interval,"outputsize":200,"apikey":TWELVE_DATA_API_KEY,"format":"JSON"}
    try:
        r=requests.get(TWELVE_DATA_URL,params=params,timeout=15,headers={"User-Agent":"gold-scalper/1.1"}); r.raise_for_status(); data=r.json()
        if data.get("status")=="error":
            print(f'Twelve Data error ({interval}): {data.get("message",data)}'); return None
        values=data.get("values")
        if not isinstance(values,list):
            print(f"Twelve Data returned no candles ({interval})"); return None
        result=[]
        for x in reversed(values):
            try: result.append({"time":x.get("datetime"),"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"])})
            except (KeyError,TypeError,ValueError): continue
        return result
    except (requests.RequestException,ValueError) as e:
        print(f"Twelve Data request error ({interval}): {e}"); return None


def snapshot(candles):
    if not candles or len(candles)<55:return None
    closed=candles[:-1]; closes=[x["close"] for x in closed]
    return {"price":closes[-1],"ema9":ema(closes[-40:],9),"ema20":ema(closes[-50:],20),"ema50":ema(closes[-55:],50),"rsi":rsi(closes),"atr":atr(closed),"candles":closed}


def trend(s):
    if s["price"]>s["ema9"]>s["ema20"]>s["ema50"]:return "BULLISH"
    if s["price"]<s["ema9"]<s["ema20"]<s["ema50"]:return "BEARISH"
    return "MIXED"


def analyze():
    c5=get_candles("5min"); c15=get_candles("15min"); c1h=get_candles("1h")
    s5,s15,s1h=snapshot(c5),snapshot(c15),snapshot(c1h)
    if not all((s5,s15,s1h)):return None
    t5,t15,t1h=trend(s5),trend(s15),trend(s1h); price,r=s5["price"],s5["rsi"]
    recent=s5["candles"][-20:]; support=min(x["low"] for x in recent); resistance=max(x["high"] for x in recent)
    score=0; side="WAIT"; reasons=[]
    if t5=="BULLISH" and r is not None and 52<=r<=72:
        side,score="BUY",50; reasons.append("زخم 5 دقائق صاعد")
        if t15=="BULLISH":score+=20;reasons.append("فريم 15 دقيقة يؤكد الشراء")
        if t1h=="BULLISH":score+=15;reasons.append("اتجاه الساعة يؤكد الشراء")
        if t15=="BEARISH":score-=20;reasons.append("فريم 15 دقيقة يعارض الشراء")
    elif t5=="BEARISH" and r is not None and 28<=r<=48:
        side,score="SELL",50; reasons.append("زخم 5 دقائق هابط")
        if t15=="BEARISH":score+=20;reasons.append("فريم 15 دقيقة يؤكد البيع")
        if t1h=="BEARISH":score+=15;reasons.append("اتجاه الساعة يؤكد البيع")
        if t15=="BULLISH":score-=20;reasons.append("فريم 15 دقيقة يعارض البيع")
    score=max(0,min(100,score))
    if score<70:side="WAIT"
    a=s5["atr"] or price*0.001
    sl=price-1.2*a if side=="BUY" else price+1.2*a if side=="SELL" else None
    tp=price+1.8*a if side=="BUY" else price-1.8*a if side=="SELL" else None
    return {"side":side,"price":price,"rsi":r,"atr":a,"support":support,"resistance":resistance,"score":score,"t5":t5,"t15":t15,"t1h":t1h,"sl":sl,"tp":tp,"reasons":reasons}


def ar_side(v):return {"BUY":"🟢 شراء","SELL":"🔴 بيع","WAIT":"🟡 انتظار"}.get(v,v)
def ar_trend(v):return {"BULLISH":"صاعد 📈","BEARISH":"هابط 📉","MIXED":"مختلط ↔️"}.get(v,v)

def message(a):
    risk="لا يوجد دخول حاليًا" if a["side"]=="WAIT" else f'🛑 وقف الخسارة: {a["sl"]:.2f}\n🏁 الهدف: {a["tp"]:.2f}'
    why="؛ ".join(a["reasons"]) or "لا توجد فرصة سكالبنج مؤكدة حاليًا"
    return (f'🥇 بوت الذهب XAU/USD — سكالبنج\n\n🎯 الإشارة: {ar_side(a["side"])}\n💰 السعر: {a["price"]:.2f}\n📌 نسبة الثقة: {a["score"]}%\n📈 RSI: {a["rsi"]:.1f}\n🌊 ATR: {a["atr"]:.2f}\n🟢 الدعم: {a["support"]:.2f}\n🔴 المقاومة: {a["resistance"]:.2f}\n\n⏱ الاتجاهات:\n5 دقائق: {ar_trend(a["t5"])}\n15 دقيقة: {ar_trend(a["t15"])}\nساعة: {ar_trend(a["t1h"])}\n\n{risk}\n🧠 السبب: {why}\n\n⚠️ تنبيه تحليلي فقط — لم يتم تنفيذ أي صفقة.')

last_signal=None; last_report=0
while True:
    a=analyze()
    if a:
        now=time.time(); print(f'XAU/USD {a["price"]:.2f} | {a["side"]} | RSI {a["rsi"]:.1f} | 5m/15m/1h {a["t5"]}/{a["t15"]}/{a["t1h"]} | ATR {a["atr"]:.2f} | Confidence {a["score"]}%')
        periodic=last_report==0 or now-last_report>=REPORT_SECONDS
        immediate=a["side"] in ("BUY","SELL") and a["side"]!=last_signal
        if periodic or immediate:
            send_telegram(message(a))
            if periodic:last_report=now
        last_signal=a["side"]
    time.sleep(30)