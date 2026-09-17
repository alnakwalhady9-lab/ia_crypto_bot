import os,time,json,requests,uuid
TOKEN=os.getenv('GOLD_TELEGRAM_BOT_TOKEN');CHAT=os.getenv('GOLD_TELEGRAM_CHAT_ID');KEY=os.getenv('ALLTICK_API_TOKEN');INVITE=os.getenv('GOLD_INVITE_CODE')
URL='https://quote.alltick.co/quote-b-api/kline';REPORT=900;cache={};TTL={'5min':300,'15min':900,'1h':3600}
KLINE_TYPE={'5min':2,'15min':3,'1h':5}
MIN_API_GAP=11;last_api_request=0
DATA_DIR='/data' if os.path.isdir('/data') and os.access('/data',os.W_OK) else '.';STATE_FILE=os.path.join(DATA_DIR,'gold_learning_state.json');SUB_FILE=os.path.join(DATA_DIR,'gold_subscribers.json')
BASE={'trend5':14,'trend15':16,'trend1h':5,'structure5':14,'structure15':10,'liquidity':20,'equal_liq':4,'price_action':12,'breakout':18,'harmonic5':18,'harmonic15':12,'rsi':7}
def load_subscribers():
 s=set([str(CHAT)]) if CHAT else set()
 try:
  with open(SUB_FILE) as f:s.update(str(x) for x in json.load(f))
 except:pass
 return s
SUBSCRIBERS=load_subscribers();telegram_offset=0
def save_subscribers():
 try:
  tmp=SUB_FILE+'.tmp'
  with open(tmp,'w') as f:json.dump(sorted(SUBSCRIBERS),f)
  os.replace(tmp,SUB_FILE)
 except Exception as e:print('Subscribers',e)
def tg_send(cid,m):
 if not TOKEN:return
 try:requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',data={'chat_id':cid,'text':m},timeout=15).raise_for_status()
 except Exception as e:print('Telegram',cid,e)
def send(m):
 for cid in list(SUBSCRIBERS):tg_send(cid,m)
def poll_commands():
 global telegram_offset
 if not TOKEN:return
 try:
  r=requests.get(f'https://api.telegram.org/bot{TOKEN}/getUpdates',params={'offset':telegram_offset,'timeout':0,'allowed_updates':'["message"]'},timeout=12);r.raise_for_status()
  for u in r.json().get('result',[]):
   telegram_offset=max(telegram_offset,int(u['update_id'])+1);q=u.get('message') or {};cid=str((q.get('chat') or {}).get('id',''));txt=(q.get('text') or '').strip()
   if not cid or not txt:continue
   if txt.startswith('/start'):
    arg=txt.split(maxsplit=1)[1].strip() if len(txt.split(maxsplit=1))>1 else ''
    if cid in SUBSCRIBERS:tg_send(cid,'✅ أنت مشترك بالفعل في إشارات الذهب.')
    elif INVITE and arg==INVITE:
     SUBSCRIBERS.add(cid);save_subscribers();tg_send(cid,'✅ تم الاشتراك في إشارات GOLD SCALPER PRO.\nلإيقافها أرسل /stop')
    else:tg_send(cid,'🔒 رابط الدعوة غير صالح.')
   elif txt.startswith('/stop'):
    if cid in SUBSCRIBERS and cid!=str(CHAT):
     SUBSCRIBERS.remove(cid);save_subscribers()
    tg_send(cid,'⛔ تم إيقاف إشارات الذهب.')
 except Exception as e:print('Telegram updates',e)
def fetch(sym,tf,n=200):
    global last_api_request
    k=f'{sym}:{tf}';now=time.time()
    if k in cache and now-cache[k][0]<TTL[tf]: return cache[k][1]
    try:
        if not KEY:
            print('AllTick: ALLTICK_API_TOKEN is missing')
            return None
        query={
            'trace':str(uuid.uuid4()),
            'data':{
                'code':'GOLD',
                'kline_type':KLINE_TYPE[tf],
                'kline_timestamp_end':0,
                'query_kline_num':min(n,1000),
                'adjust_type':0
            }
        }
        wait_for=MIN_API_GAP-(time.time()-last_api_request)
        if wait_for>0:
            time.sleep(wait_for)
        last_api_request=time.time()
        r=requests.get(
            URL,
            params={'token':KEY,'query':json.dumps(query,separators=(',',':'))},
            timeout=(5,20)
        )
        if r.status_code==429:
            print('AllTick rate limit (429); retrying later')
            return cache.get(k,(0,None))[1]
        if not r.ok:
            print('AllTick HTTP error:',r.status_code)
            return cache.get(k,(0,None))[1]
        payload=r.json()
        rows=(payload.get('data') or {}).get('kline_list') or []
        out=[]
        for z in rows:
            try:
                out.append({
                    't':z.get('timestamp'),
                    'o':float(z['open_price']),
                    'h':float(z['high_price']),
                    'l':float(z['low_price']),
                    'c':float(z['close_price'])
                })
            except (KeyError,TypeError,ValueError):
                continue
        out.sort(key=lambda x:int(x['t'] or 0))
        if not out:
            print('AllTick:',payload.get('msg') or payload.get('message') or 'empty kline response')
            return None
        cache[k]=(now,out)
        return out
    except Exception as e:
        print('AllTick error:',type(e).__name__)
        return cache.get(k,(0,None))[1]

live_cache=[0,None]
def fetch_live():
 # Refresh the live candle every 30 seconds so TP/SL alerts are timely,
 # while keeping API usage controlled.
 global last_api_request
 now=time.time()
 if live_cache[1] is not None and now-live_cache[0]<30:
  return live_cache[1]
 try:
  if not KEY:return live_cache[1]
  query={'trace':str(uuid.uuid4()),'data':{'code':'GOLD','kline_type':KLINE_TYPE['5min'],'kline_timestamp_end':0,'query_kline_num':2,'adjust_type':0}}
  wait_for=MIN_API_GAP-(time.time()-last_api_request)
  if wait_for>0:time.sleep(wait_for)
  last_api_request=time.time()
  r=requests.get(URL,params={'token':KEY,'query':json.dumps(query,separators=(',',':'))},timeout=(5,20))
  if not r.ok:return live_cache[1]
  rows=(r.json().get('data') or {}).get('kline_list') or []
  if not rows:return live_cache[1]
  z=max(rows,key=lambda q:int(q.get('timestamp') or 0))
  candle={'t':z.get('timestamp'),'o':float(z['open_price']),'h':float(z['high_price']),'l':float(z['low_price']),'c':float(z['close_price'])}
  live_cache[:]=[now,candle]
  return candle
 except Exception as e:
  print('AllTick live error:',type(e).__name__)
  return live_cache[1]
def ema(v,p):
 k=2/(p+1);x=v[0]
 for z in v[1:]:x=z*k+x*(1-k)
 return x
def rsi(v,p=14):
 d=[v[i]-v[i-1] for i in range(1,len(v))];g=sum(max(x,0) for x in d[-p:])/p;l=sum(max(-x,0) for x in d[-p:])/p
 return 100 if l==0 else 100-100/(1+g/l)
def atr(c,p=14):
 t=[]
 for i in range(1,len(c)):t.append(max(c[i]['h']-c[i]['l'],abs(c[i]['h']-c[i-1]['c']),abs(c[i]['l']-c[i-1]['c'])))
 return sum(t[-p:])/p
def snap(c):
 if not c or len(c)<65:return None
 # AllTick includes the candle that is still forming.  Signals must only use
 # completed candles; otherwise a temporary wick can flip the direction.
 c=c[:-1];v=[x['c'] for x in c];return {'p':v[-1],'e9':ema(v[-50:],9),'e20':ema(v[-60:],20),'e50':ema(v[-65:],50),'r':rsi(v),'a':atr(c),'c':c}
def candle_is_fresh(s,tf):
 try:
  ts=float(s['c'][-1]['t'])
  if ts>1e12:ts/=1000
  # The newest completed candle may legitimately be almost two intervals old.
  return 0<=time.time()-ts<=TTL[tf]*2.25
 except:return False
def trend(s):
 if s['p']>s['e9']>s['e20']>s['e50']:return 'UP'
 if s['p']<s['e9']<s['e20']<s['e50']:return 'DOWN'
 return 'MIXED'
def pivots(c,L=2,R=2):
 q=[]
 for i in range(L,len(c)-R):
  if c[i]['h']==max(x['h'] for x in c[i-L:i+R+1]):q.append((i,c[i]['h'],'H'))
  if c[i]['l']==min(x['l'] for x in c[i-L:i+R+1]):q.append((i,c[i]['l'],'L'))
 q.sort();out=[]
 for p in q:
  if out and out[-1][2]==p[2]:
   if (p[2]=='H' and p[1]>out[-1][1]) or (p[2]=='L' and p[1]<out[-1][1]):out[-1]=p
  else:out.append(p)
 return out
def structure(c):
 ps=pivots(c[-100:]);hs=[x for x in ps if x[2]=='H'][-2:];ls=[x for x in ps if x[2]=='L'][-2:]
 if len(hs)==2 and len(ls)==2:
  if hs[-1][1]>hs[-2][1] and ls[-1][1]>ls[-2][1]:return 'BULLISH'
  if hs[-1][1]<hs[-2][1] and ls[-1][1]<ls[-2][1]:return 'BEARISH'
 return 'RANGE'
def levels(c):
 ps=pivots(c[-120:]);p=c[-1]['c'];lo=sorted([x[1] for x in ps if x[2]=='L' and x[1]<=p],reverse=True);hi=sorted([x[1] for x in ps if x[2]=='H' and x[1]>=p])
 return (lo[0] if lo else min(x['l'] for x in c[-30:])),(hi[0] if hi else max(x['h'] for x in c[-30:]))
def liquidity(c,a):
 prev=c[-25:-1];last=c[-1];ps=pivots(prev);hs=sorted([x[1] for x in ps if x[2]=='H']);ls=sorted([x[1] for x in ps if x[2]=='L']);buy=sell=False
 if hs and last['h']>hs[-1] and last['c']<hs[-1]:sell=True
 if ls and last['l']<ls[0] and last['c']>ls[0]:buy=True
 tol=max(a*.18,last['c']*.00012);eqh=any(abs(hs[i]-hs[i-1])<=tol for i in range(1,len(hs)));eql=any(abs(ls[i]-ls[i-1])<=tol for i in range(1,len(ls)))
 return {'buy':buy,'sell':sell,'eqh':eqh,'eql':eql}
def price_action(c):
 x=c[-1];p=c[-2];body=abs(x['c']-x['o']);rng=max(x['h']-x['l'],1e-9);bull=x['c']>x['o'] and x['c']>p['h'];bear=x['c']<x['o'] and x['c']<p['l'];pb=(min(x['o'],x['c'])-x['l'])>body*2 and body/rng<.45;ps=(x['h']-max(x['o'],x['c']))>body*2 and body/rng<.45
 return 'BULLISH' if bull or pb else 'BEARISH' if bear or ps else 'NEUTRAL'
def breakout(c,sup,res,a):
 x=c[-1];p=c[-2];b=a*.08
 if x['c']>res+b:return 'BULL_BREAK'
 if x['c']<sup-b:return 'BEAR_BREAK'
 if p['c']>res and x['l']<=res+b and x['c']>res:return 'BULL_RETEST'
 if p['c']<sup and x['h']>=sup-b and x['c']<sup:return 'BEAR_RETEST'
 return 'NONE'
def near(x,t,z=.12):return t*(1-z)<=x<=t*(1+z)
def harmonic(c):
 ps=pivots(c[-130:],3,3);best=None
 for q in range(max(0,len(ps)-12),max(0,len(ps)-4)):
  P=ps[q:q+5]
  if len(P)<5:continue
  X,A,B,C,D=[x[1] for x in P];XA=abs(A-X);AB=abs(B-A);BC=abs(C-B);CD=abs(D-C);AD=abs(D-A)
  if min(XA,AB,BC,CD)==0:continue
  ab,bc,cd,ad=AB/XA,BC/AB,CD/BC,AD/XA;name=None
  if near(ab,.618,.10) and .382<=bc<=.886 and 1.13<=cd<=1.75 and near(ad,.786,.12):name='Gartley'
  elif .382<=ab<=.50 and .382<=bc<=.886 and 1.5<=cd<=2.7 and near(ad,.886,.12):name='Bat'
  elif near(ab,.786,.12) and .382<=bc<=.886 and 1.5<=cd<=2.7 and 1.15<=ad<=1.40:name='Butterfly'
  elif .382<=ab<=.618 and .382<=bc<=.886 and 2<=cd<=3.8 and 1.45<=ad<=1.75:name='Crab'
  elif .70<=AB/CD<=1.30 and .45<=bc<=.90:name='ABCD'
  if name:best={'name':name,'side':'BUY' if P[-1][2]=='L' else 'SELL'}
 return best
def default_state():return {'next_id':1,'active':[],'history':[],'weights':{k:1.0 for k in BASE},'last_learn_count':0}
def load_state():
 try:
  with open(STATE_FILE) as f:s=json.load(f)
  for k in BASE:s.setdefault('weights',{}).setdefault(k,1.0)
  s.setdefault('history',[]);s.setdefault('active',[]);s.setdefault('next_id',1);s.setdefault('last_learn_count',0);return s
 except:return default_state()
def save_state():
 try:
  tmp=STATE_FILE+'.tmp'
  with open(tmp,'w') as f:json.dump(state,f,ensure_ascii=False)
  os.replace(tmp,STATE_FILE)
 except Exception as e:print('State',e)
def W(k):return BASE[k]*state['weights'].get(k,1.0)
def learn():
 closed=len(state['history'])
 if closed<20 or closed-state.get('last_learn_count',0)<10:return
 stats={k:[0,0] for k in BASE}
 for s in state['history'][-200:]:
  win=s.get('max_tp',0)>=1
  for f in s.get('features',[]):
   if f in stats:stats[f][0]+=1;stats[f][1]+=int(win)
 changed=[]
 for k,(n,wins) in stats.items():
  if n<10:continue
  rate=wins/n;target=max(.75,min(1.25,.75+.5*rate));old=state['weights'].get(k,1.0);new=round(.75*old+.25*target,3)
  if abs(new-old)>=.01:state['weights'][k]=new;changed.append((k,new,round(rate,2),n))
 state['last_learn_count']=closed;save_state();print('LEARN',changed)
def analyze():
 s5=snap(fetch('XAU/USD','5min'));s15=snap(fetch('XAU/USD','15min'));s1=snap(fetch('XAU/USD','1h'))
 if not all((s5,s15,s1)):return None
 if not (candle_is_fresh(s5,'5min') and candle_is_fresh(s15,'15min') and candle_is_fresh(s1,'1h')):
  print('SIGNAL BLOCKED: stale AllTick candle data')
  return None
 p=s5['p'];a=s5['a'];sup,res=levels(s5['c']);st5=structure(s5['c']);st15=structure(s15['c']);liq=liquidity(s5['c'],a);pa=price_action(s5['c']);br=breakout(s5['c'],sup,res,a);h5=harmonic(s5['c']);h15=harmonic(s15['c']);t5,t15,t1=trend(s5),trend(s15),trend(s1);buy=sell=0;why=[];fb=[];fs=[]
 def add(k,side,text=None):
  nonlocal buy,sell
  if side=='BUY':buy+=W(k);fb.append(k)
  else:sell+=W(k);fs.append(k)
  if text:why.append(text)
 if t5=='UP':add('trend5','BUY')
 elif t5=='DOWN':add('trend5','SELL')
 if t15=='UP':add('trend15','BUY')
 elif t15=='DOWN':add('trend15','SELL')
 if t1=='UP':add('trend1h','BUY')
 elif t1=='DOWN':add('trend1h','SELL')
 if st5=='BULLISH':add('structure5','BUY','هيكل 5m صاعد')
 elif st5=='BEARISH':add('structure5','SELL','هيكل 5m هابط')
 if st15=='BULLISH':add('structure15','BUY')
 elif st15=='BEARISH':add('structure15','SELL')
 if liq['buy']:add('liquidity','BUY','Liquidity sweep BUY')
 if liq['sell']:add('liquidity','SELL','Liquidity sweep SELL')
 if liq['eql']:add('equal_liq','BUY','قيعان متساوية')
 if liq['eqh']:add('equal_liq','SELL','قمم متساوية')
 if pa=='BULLISH':add('price_action','BUY','Price Action صاعد')
 elif pa=='BEARISH':add('price_action','SELL','Price Action هابط')
 if br.startswith('BULL'):add('breakout','BUY','كسر/إعادة اختبار صاعد')
 elif br.startswith('BEAR'):add('breakout','SELL','كسر/إعادة اختبار هابط')
 if h5:add('harmonic5',h5['side'],f'Harmonic 5m {h5["name"]} {h5["side"]}')
 if h15:add('harmonic15',h15['side'],f'Harmonic 15m {h15["name"]} {h15["side"]}')
 if s5['r']<35:add('rsi','BUY')
 elif s5['r']>65:add('rsi','SELL')
 total=max(buy+sell,1);bp=round(100*buy/total);sp=100-bp;side='BUY' if bp>=65 and buy>=sell+W('price_action') else 'SELL' if sp>=65 and sell>=buy+W('price_action') else 'WAIT'
 # 15m and 1h define the market direction.  The 5m chart is entry timing
 # only: a counter-trend RSI, liquidity sweep or harmonic pattern can no
 # longer overrule a falling higher timeframe.
 if side=='BUY' and not (t15=='UP' and t1=='UP'):
  side='WAIT';why.append('منع BUY: اتجاه 15m و1h غير صاعد معًا')
 elif side=='SELL' and not (t15=='DOWN' and t1=='DOWN'):
  side='WAIT';why.append('منع SELL: اتجاه 15m و1h غير هابط معًا')
 ranges=[x['h']-x['l'] for x in s5['c'][-15:-1]];spike=(s5['c'][-1]['h']-s5['c'][-1]['l'])>max(sum(ranges)/len(ranges)*2.5,a*2)
 if spike:side='WAIT';why.append('تقلب غير طبيعي — حماية الدخول')
 sl=p-1.15*a if side=='BUY' else p+1.15*a if side=='SELL' else None;tp1=p+1.1*a if side=='BUY' else p-1.1*a if side=='SELL' else None;tp2=p+1.7*a if side=='BUY' else p-1.7*a if side=='SELL' else None;tp3=p+2.4*a if side=='BUY' else p-2.4*a if side=='SELL' else None;features=fb if side=='BUY' else fs if side=='SELL' else []
 return locals()
def ar(x):return {'BUY':'🟢 شراء','SELL':'🔴 بيع','WAIT':'🟡 انتظار','UP':'صاعد','DOWN':'هابط','MIXED':'مختلط','BULLISH':'صاعد','BEARISH':'هابط','RANGE':'عرضي','NEUTRAL':'محايد'}.get(x,x)
def gold_pips(entry,target):return int(round(abs(target-entry)*100))
def msg(x):
 if state['active']:
  sig=state['active'][0];e=sig['entry'];t=sig['tps']
  risk=f'📌 صفقة #{sig["id"]} مفتوحة: {ar(sig["side"])}\n📍 Entry: {e:.2f}\n🛑 SL: {sig["sl"]:.2f}\n🎯 TP1: {t[0]:.2f} (+{gold_pips(e,t[0])} pips)\n🎯 TP2: {t[1]:.2f} (+{gold_pips(e,t[1])} pips)\n🎯 TP3: {t[2]:.2f} (+{gold_pips(e,t[2])} pips)'
  status='✅ الصفقة مسجلة وتحت المتابعة — لن تُفتح إشارة أخرى قبل TP3 أو SL.'
 else:
  risk='لا دخول مؤكد حاليًا' if x['side']=='WAIT' else f'📍 Entry محتمل: {x["p"]:.2f}\n🛑 SL: {x["sl"]:.2f}\n🎯 TP1: {x["tp1"]:.2f} (+{gold_pips(x["p"],x["tp1"])} pips)\n🎯 TP2: {x["tp2"]:.2f} (+{gold_pips(x["p"],x["tp2"])} pips)\n🎯 TP3: {x["tp3"]:.2f} (+{gold_pips(x["p"],x["tp3"])} pips)'
  status='⚠️ تحليل احتمالي فقط — لا توجد صفقة مفتوحة.'
 h5=x['h5']['name']+' '+ar(x['h5']['side']) if x['h5'] else 'لا يوجد';h15=x['h15']['name']+' '+ar(x['h15']['side']) if x['h15'] else 'لا يوجد'
 return f'🥇 GOLD SCALPER PRO\n\n🎯 القرار: {ar(x["side"])}\n💰 XAU/USD: {x["p"]:.2f}\n🟢 ميل الشراء: {x["bp"]}% | 🔴 ميل البيع: {x["sp"]}%\n📐 كلاسيكي 5m: {ar(x["st5"])} | 15m: {ar(x["st15"])}\n📊 EMA 5m/15m/1h: {ar(x["t5"])} / {ar(x["t15"])} / {ar(x["t1"])}\n🕯 Price Action: {ar(x["pa"])}\n💧 Liquidity: {"Sweep BUY" if x["liq"]["buy"] else "Sweep SELL" if x["liq"]["sell"] else "لا Sweep مؤكد"}\n🟢 دعم: {x["sup"]:.2f} | 🔴 مقاومة: {x["res"]:.2f}\n🧬 Harmonic 5m: {h5}\n🧬 Harmonic 15m: {h15}\n📈 RSI: {x["s5"]["r"]:.1f} | ATR: {x["a"]:.2f}\n\n{risk}\n🧠 التوافق: {"؛ ".join(x["why"][:7]) if x["why"] else "توافق ضعيف"}\n🧠 Adaptive learning: ON\n{status}'
def stats_text():
 h=state['history'];n=len(h);w=sum(x.get('max_tp',0)>=1 for x in h);t3=sum(x.get('max_tp',0)>=3 for x in h)
 return f'📊 سجل التعلم: {n} مغلقة | TP1+ {w} ({w/n*100:.1f}%) | TP3 {t3}' if n else '📊 سجل التعلم: لا توجد نتائج مغلقة بعد'
def open_signal(x):
 if state['active']:
  print('SIGNAL BLOCKED: an earlier gold signal is still active')
  return False
 sig={'id':state['next_id'],'side':x['side'],'entry':x['p'],'sl':x['sl'],'tps':[x['tp1'],x['tp2'],x['tp3']],'hit':[False]*3,'max_tp':0,'features':x['features'],'buy_pct':x['bp'],'sell_pct':x['sp'],'opened_at':time.time()};state['next_id']+=1;state['active'].append(sig);save_state();return True
def close_signal(sig,result,price):
 global last
 sig['result']=result;sig['exit_price']=price;sig['closed_at']=time.time();state['history'].append(sig.copy());state['history']=state['history'][-500:];state['active'].remove(sig);last=None;save_state();learn()
def track_live(c):
 if not state['active'] or not c:return
 hi,lo=c['h'],c['l']
 for sig in list(state['active']):
  stop=lo<=sig['sl'] if sig['side']=='BUY' else hi>=sig['sl']
  tp3=hi>=sig['tps'][2] if sig['side']=='BUY' else lo<=sig['tps'][2]
  # If SL and TP3 are both inside the same 1m candle, ordering is unknown: record the conservative SL outcome.
  if stop and tp3:
   close_signal(sig,'SL_AMBIGUOUS',sig['sl']);send(f'❌ GOLD SIGNAL #{sig["id"]} — SL HIT (نفس شمعة TP/SL)\n{stats_text()}');continue
  touch=(lambda z:hi>=z) if sig['side']=='BUY' else (lambda z:lo<=z)
  for i,t in enumerate(sig['tps']):
   if not sig['hit'][i] and touch(t):
    sig['hit'][i]=True;sig['max_tp']=max(sig['max_tp'],i+1);save_state();send(f'✅ GOLD SIGNAL #{sig["id"]} — TP{i+1} HIT\n🎯 الهدف: {t:.2f}\n📈 المحقق: +{gold_pips(sig["entry"],t)} pips')
  if sig['hit'][2]:close_signal(sig,'TP3',sig['tps'][2]);send(f'🏁 GOLD SIGNAL #{sig["id"]} اكتملت — TP3\n{stats_text()}');continue
  if stop:close_signal(sig,'SL_AFTER_TP'+str(sig['max_tp']) if sig['max_tp'] else 'SL',sig['sl']);send(f'❌ GOLD SIGNAL #{sig["id"]} — SL HIT\n🎯 أعلى هدف: TP{sig["max_tp"]}\n{stats_text()}')
state=load_state();print('Gold learning state:',STATE_FILE,'history=',len(state['history']),'active=',len(state['active']),'weights=',state['weights'])
last=None;last_report=time.time();last_analysis=0
while True:
 poll_commands()
 live=fetch_live()
 if live:
  track_live(live);print(f'LIVE XAU {live["c"]:.2f} H={live["h"]:.2f} L={live["l"]:.2f} active={len(state["active"])}')
 now=time.time()
 if now-last_analysis>=30:
  x=analyze();last_analysis=now
  if x:
   print(f'XAU {x["p"]:.2f} {x["side"]} BUY={x["bp"]}% SELL={x["sp"]}%')
   has_active=bool(state['active'])
   periodic=now-last_report>=REPORT
   immediate=(not has_active) and x['side'] in ('BUY','SELL') and x['side']!=last
   opened=open_signal(x) if immediate else False
   if periodic or opened:
    send(msg(x))
    if periodic:last_report=now
   if not state['active']:last=x['side']
 time.sleep(15)
