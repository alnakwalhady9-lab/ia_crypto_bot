import os,time,json,secrets,requests,uuid,re,datetime,xml.etree.ElementTree as ET
from urllib.parse import quote_plus
TOKEN=os.getenv('GOLD_TELEGRAM_BOT_TOKEN');CHAT=os.getenv('GOLD_TELEGRAM_CHAT_ID');KEY=os.getenv('ALLTICK_API_TOKEN');TWELVE=os.getenv('TWELVE_DATA_API_KEY');INVITE=os.getenv('GOLD_INVITE_CODE')
# Safety default: paper-test every signal and never broadcast entries until explicitly approved.
PAPER_MODE=os.getenv('GOLD_PAPER_MODE','true').strip().lower() not in ('0','false','off','no')
STARTED_AT=time.time()
URL='https://quote.alltick.co/quote-b-api/kline';REPORT=900;cache={};TTL={'5min':300,'15min':900,'1h':3600}
KLINE_TYPE={'5min':2,'15min':3,'1h':5}
MIN_API_GAP=15;API_BACKOFF=300;last_api_request=0;api_blocked_until=0
DATA_DIR='/data' if os.path.isdir('/data') and os.access('/data',os.W_OK) else '.';STATE_FILE=os.path.join(DATA_DIR,'gold_learning_state.json');SUB_FILE=os.path.join(DATA_DIR,'gold_subscribers.json');INVITE_FILE=os.path.join(DATA_DIR,'gold_invite.json');NEWS_SEEN_FILE=os.path.join(DATA_DIR,'gold_news_seen.json')
BASE={'trend5':14,'trend15':16,'trend1h':5,'structure5':14,'structure15':10,'liquidity':20,'equal_liq':4,'price_action':12,'breakout':18,'harmonic5':18,'harmonic15':12,'rsi':7}
NEWS_REFRESH=60;NEWS_BLOCK_MINUTES=15;news_cache={'t':0,'v':{'bias':'NEUTRAL','score':0,'block':False,'headline':'لا خبر عاجل مؤكد','items':[]}}
ESCALATION={'attack','attacks','strike','strikes','bomb','missile','drone','retaliation','escalat','blockade','hormuz','killed','war expands','military action','threatens'}
EASING={'ceasefire','deal','talks','negotiat','peace','war nearing end','towards end','toward end','de-escalat','agreement','diplomacy'}
def load_subscribers():
 s=set([str(CHAT)]) if CHAT else set()
 try:
  with open(SUB_FILE) as f:s.update(str(x) for x in json.load(f))
 except:pass
 return s
def load_invite():
 try:
  with open(INVITE_FILE) as f:return str(json.load(f).get('code') or '')
 except:return str(INVITE or '')
def save_invite():
 try:
  tmp=INVITE_FILE+'.tmp'
  with open(tmp,'w') as f:json.dump({'code':INVITE_CODE},f)
  os.replace(tmp,INVITE_FILE)
 except Exception as e:print('Invite',e)
SUBSCRIBERS=load_subscribers();INVITE_CODE=load_invite();telegram_offset=0
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
def trade_send(m):
 # Paper results are logged and clearly labelled in Telegram.
 clean=str(m).replace('\\n',' | ')
 if PAPER_MODE:
  print('PAPER RESULT:',clean)
  send('🧪 نتيجة صفقة تجريبية — لا تدخل بأموال حقيقية\n'+str(m))
 else:send(m)
def news_key(title):
 # Ignore case, spacing and the publisher suffix so syndicated copies of the
 # same headline are treated as one alert.
 title=str(title or '').replace('\\n',' ').replace('\\r',' ')
 title=re.sub(r'\s+',' ',title).strip().lower()
 title=re.sub(r'\s+-\s+[^-]{2,45}$','',title)
 return re.sub(r'[^a-z0-9]+',' ',title).strip()
def load_news_seen():
 try:
  with open(NEWS_SEEN_FILE) as f:data=json.load(f)
  cutoff=time.time()-86400
  return {'last_sent':float(data.get('last_sent',0)),'keys':{str(k):float(v) for k,v in data.get('keys',{}).items() if float(v)>=cutoff}}
 except:return {'last_sent':0,'keys':{}}
def save_news_seen():
 try:
  tmp=NEWS_SEEN_FILE+'.tmp'
  with open(tmp,'w') as f:json.dump(news_seen,f)
  os.replace(tmp,NEWS_SEEN_FILE)
 except Exception as e:print('News seen',e)
news_seen=load_news_seen()
def poll_commands():
 global telegram_offset,INVITE_CODE
 if not TOKEN:return
 try:
  r=requests.get(f'https://api.telegram.org/bot{TOKEN}/getUpdates',params={'offset':telegram_offset,'timeout':0,'allowed_updates':'["message"]'},timeout=12);r.raise_for_status()
  for u in r.json().get('result',[]):
   telegram_offset=max(telegram_offset,int(u['update_id'])+1);q=u.get('message') or {};cid=str((q.get('chat') or {}).get('id',''));txt=(q.get('text') or '').strip()
   if not cid or not txt:continue
   if txt.startswith('/start'):
    arg=txt.split(maxsplit=1)[1].strip() if len(txt.split(maxsplit=1))>1 else ''
    if cid in SUBSCRIBERS:tg_send(cid,'✅ أنت مشترك بالفعل في إشارات الذهب.')
    elif INVITE_CODE and secrets.compare_digest(arg,INVITE_CODE):
     SUBSCRIBERS.add(cid);save_subscribers();tg_send(cid,'✅ تم الاشتراك في إشارات GOLD SCALPER PRO.\nلإيقافها أرسل /stop')
    else:tg_send(cid,'🔒 رابط الدعوة غير صالح.')
   elif txt.startswith('/invite') and cid==str(CHAT):
    INVITE_CODE=secrets.token_urlsafe(6);save_invite()
    try:
     me=requests.get(f'https://api.telegram.org/bot{TOKEN}/getMe',timeout=10).json().get('result',{});username=me.get('username','')
     link=f'https://t.me/{username}?start={INVITE_CODE}' if username else f'رمز الدعوة: {INVITE_CODE}'
     tg_send(cid,'🔐 رابط دعوة خاص جديد:\n'+link+'\n\nأي رابط قديم توقف.')
    except Exception as e:tg_send(cid,f'🔐 رمز الدعوة الجديد: {INVITE_CODE}')
   elif txt.startswith('/stop'):
    if cid in SUBSCRIBERS and cid!=str(CHAT):
     SUBSCRIBERS.remove(cid);save_subscribers()
    tg_send(cid,'⛔ تم إيقاف إشارات الذهب.')
 except Exception as e:print('Telegram updates error:',type(e).__name__)
def fetch_twelve(tf,n=200):
    if not TWELVE:
        print('Twelve Data: TWELVE_DATA_API_KEY is missing')
        return None
    try:
        r=requests.get(
            'https://api.twelvedata.com/time_series',
            params={'symbol':'XAU/USD','interval':tf,'outputsize':min(n,5000),'timezone':'UTC','apikey':TWELVE},
            timeout=(5,20)
        )
        if not r.ok:
            print('Twelve Data HTTP error:',r.status_code)
            return None
        payload=r.json()
        rows=payload.get('values') or []
        out=[]
        for z in rows:
            try:
                ts=int(datetime.datetime.strptime(z['datetime'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc).timestamp())
                out.append({'t':ts,'o':float(z['open']),'h':float(z['high']),'l':float(z['low']),'c':float(z['close'])})
            except (KeyError,TypeError,ValueError):
                continue
        out.sort(key=lambda x:int(x['t'] or 0))
        if not out:
            print('Twelve Data:',payload.get('message') or payload.get('status') or 'empty response')
            return None
        print(f'DATA FALLBACK: Twelve Data {tf} rows={len(out)}')
        return out
    except Exception as e:
        print('Twelve Data error:',type(e).__name__)
        return None

def fetch(sym,tf,n=200):
    global last_api_request,api_blocked_until
    k=f'{sym}:{tf}';now=time.time()
    if k in cache and now-cache[k][0]<TTL[tf]: return cache[k][1]
    if now<api_blocked_until:
        fallback=fetch_twelve(tf,n)
        if fallback:cache[k]=(now,fallback)
        return fallback or cache.get(k,(0,None))[1]
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
            api_blocked_until=time.time()+API_BACKOFF
            print('AllTick rate limit (429); using Twelve Data fallback')
            fallback=fetch_twelve(tf,n)
            if fallback:cache[k]=(now,fallback)
            return fallback or cache.get(k,(0,None))[1]
        if not r.ok:
            print('AllTick HTTP error:',r.status_code)
            return cache.get(k,(0,None))[1]
        payload=r.json()
        provider_msg=str(payload.get('msg') or payload.get('message') or '').lower()
        if 'too many requests' in provider_msg or 'rate limit' in provider_msg:
            api_blocked_until=time.time()+API_BACKOFF
            print('AllTick rate limit payload; using Twelve Data fallback')
            fallback=fetch_twelve(tf,n)
            if fallback:cache[k]=(now,fallback)
            return fallback or cache.get(k,(0,None))[1]
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
 # Refresh the live candle every 60 seconds; this stays timely enough for
 # paper TP/SL tracking while respecting the provider's free-tier limits.
 global last_api_request,api_blocked_until
 now=time.time()
 live_ttl=300 if now<api_blocked_until else 60
 if live_cache[1] is not None and now-live_cache[0]<live_ttl:
  return live_cache[1]
 try:
  if now<api_blocked_until:
   rows=fetch_twelve('5min',2)
   if rows:
    live_cache[:]=[now,rows[-1]]
    return live_cache[1]
   return live_cache[1]
  if not KEY:return live_cache[1]
  query={'trace':str(uuid.uuid4()),'data':{'code':'GOLD','kline_type':KLINE_TYPE['5min'],'kline_timestamp_end':0,'query_kline_num':2,'adjust_type':0}}
  wait_for=MIN_API_GAP-(time.time()-last_api_request)
  if wait_for>0:time.sleep(wait_for)
  last_api_request=time.time()
  r=requests.get(URL,params={'token':KEY,'query':json.dumps(query,separators=(',',':'))},timeout=(5,20))
  if r.status_code==429:
   api_blocked_until=time.time()+API_BACKOFF
   print('AllTick live rate limit (429); using Twelve Data fallback')
   rows=fetch_twelve('5min',2)
   if rows:live_cache[:]=[now,rows[-1]]
   return live_cache[1]
  if not r.ok:return live_cache[1]
  payload=r.json();provider_msg=str(payload.get('msg') or payload.get('message') or '').lower()
  if 'too many requests' in provider_msg or 'rate limit' in provider_msg:
   api_blocked_until=time.time()+API_BACKOFF
   print('AllTick live rate limit payload; using Twelve Data fallback')
   rows=fetch_twelve('5min',2)
   if rows:live_cache[:]=[now,rows[-1]]
   return live_cache[1]
  rows=(payload.get('data') or {}).get('kline_list') or []
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
  # Providers can publish the just-closed bar a little late.  Allow up to
  # three and a half intervals, but never reuse an indefinitely stale feed.
  return 0<=time.time()-ts<=TTL[tf]*3.5
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
def geopolitical_news():
 global news_cache
 now=time.time()
 if now-news_cache['t']<NEWS_REFRESH:return news_cache['v']
 query=quote_plus('(Trump Iran) OR (Iran war) OR (Strait of Hormuz) OR (Israel Iran) when:1h')
 url=f'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'
 items=[];score=0
 try:
  r=requests.get(url,timeout=(5,15),headers={'User-Agent':'Mozilla/5.0 GOLD-SCALPER/3.0'});r.raise_for_status()
  root=ET.fromstring(r.content)
  for item in root.findall('.//item')[:25]:
   title=re.sub(r'\s+',' ',item.findtext('title') or '').strip()
   pub=item.findtext('pubDate') or ''
   low=title.lower()
   if not title or not any(k in low for k in ('iran','trump','hormuz','israel','gulf','houthi')):continue
   esc=sum(1 for k in ESCALATION if k in low);ease=sum(1 for k in EASING if k in low)
   impact=esc-ease
   if impact:items.append({'title':title,'impact':impact,'pub':pub});score+=max(-2,min(2,impact))
  bias='ESCALATION' if score>=2 else 'EASING' if score<=-2 else 'NEUTRAL'
  # A strong headline activates news-scalping mode. Entry still requires
  # price confirmation; the headline alone never opens a trade.
  strong=next((x for x in items if abs(x['impact'])>=1),None)
  v={'bias':bias,'score':score,'block':bool(strong),'headline':strong['title'] if strong else 'لا خبر عاجل مؤكد','items':items[:8]}
  news_cache={'t':now,'v':v};return v
 except Exception as e:
  print('NEWS error:',type(e).__name__)
  return news_cache['v']

def notify_breaking(news):
 if not news.get('block'):return
 title=str(news.get('headline','')).replace('\\n',' ').replace('\\r',' ')
 title=re.sub(r'\s+',' ',title).strip();key=news_key(title);now=time.time()
 if not key or key in news_seen['keys']:return
 # Do not flood Telegram with several rewrites of the same developing story.
 if now-news_seen['last_sent']<NEWS_BLOCK_MINUTES*60:return
 news_seen['keys'][key]=now;news_seen['last_sent']=now
 news_seen['keys']={k:v for k,v in news_seen['keys'].items() if v>=now-86400}
 save_news_seen()
 mood='تصعيد — دعم محتمل للذهب' if news['bias']=='ESCALATION' else 'تهدئة — ضغط محتمل على الذهب' if news['bias']=='EASING' else 'متضارب'
 send(f'🚨 خبر عاجل مؤثر على الذهب\n{title}\n📰 التصنيف: {mood}\n⏸ حماية الأخبار: إيقاف أي دخول جديد 15 دقيقة. الخبر لا يحدد شراء أو بيع.')

def default_state():return {'next_id':1,'active':[],'history':[],'weights':{k:1.0 for k in BASE},'last_learn_count':0,'last_open_bar':None,'last_closed_at':0}
def load_state():
 try:
  with open(STATE_FILE) as f:s=json.load(f)
  for k in BASE:s.setdefault('weights',{}).setdefault(k,1.0)
  s.setdefault('history',[]);s.setdefault('active',[]);s.setdefault('next_id',1);s.setdefault('last_learn_count',0);s.setdefault('last_open_bar',None);s.setdefault('last_closed_at',0);return s
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
  print('SIGNAL BLOCKED: stale AllTick candle data', 'ages=', {tf:round(time.time()-(float(ss['c'][-1]['t'])/(1000 if float(ss['c'][-1]['t'])>1e12 else 1))) for tf,ss in [('5m',s5),('15m',s15),('1h',s1)]})
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
 news=geopolitical_news()
 # News is informational and protective only. It must never add BUY/SELL
 # points or override the technical direction.
 total=max(buy+sell,1);bp=round(100*buy/total);sp=100-bp;side='BUY' if bp>=65 and buy>=sell+W('price_action') else 'SELL' if sp>=65 and sell>=buy+W('price_action') else 'WAIT'
 ranges=[x['h']-x['l'] for x in s5['c'][-15:-1]]
 lastbar=s5['c'][-1];prevbar=s5['c'][-2]
 # Strategic v2 gate: enter only when all three trading timeframes agree.
 # This is the single post-loss strategy change; scoring and SL/TP stay unchanged.
 if side=='BUY' and not (t5=='UP' and t15=='UP' and t1=='UP'):
  side='WAIT';why.append('منع BUY: اتجاه 5m و15m و1h غير صاعد معًا')
 elif side=='SELL' and not (t5=='DOWN' and t15=='DOWN' and t1=='DOWN'):
  side='WAIT';why.append('منع SELL: اتجاه 5m و15m و1h غير هابط معًا')
 news_pause=max(0,NEWS_BLOCK_MINUTES*60-(time.time()-float(news_seen.get('last_sent',0))))
 if news_pause>0:
  side='WAIT';why.append(f'حماية خبر قوي: متبقي {int(news_pause//60)+1} دقائق')
 spike=(lastbar['h']-lastbar['l'])>max(sum(ranges)/len(ranges)*2.5,a*2)
 if spike:side='WAIT';why.append('تقلب غير طبيعي — حماية الدخول')
 sl=p-1.15*a if side=='BUY' else p+1.15*a if side=='SELL' else None
 tp1=p+1.1*a if side=='BUY' else p-1.1*a if side=='SELL' else None
 tp2=p+1.7*a if side=='BUY' else p-1.7*a if side=='SELL' else None
 tp3=p+2.4*a if side=='BUY' else p-2.4*a if side=='SELL' else None
 features=fb if side=='BUY' else fs if side=='SELL' else []
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
 news_label={'ESCALATION':'🔴 تصعيد','EASING':'🟢 تهدئة','NEUTRAL':'⚪ محايد'}.get(x['news']['bias'],'⚪ محايد')
 return f'🥇 GOLD SCALPER PRO\n\n🎯 القرار: {ar(x["side"])}\n💰 XAU/USD: {x["p"]:.2f}\n🟢 ميل الشراء: {x["bp"]}% | 🔴 ميل البيع: {x["sp"]}%\n📐 كلاسيكي 5m: {ar(x["st5"])} | 15m: {ar(x["st15"])}\n📊 EMA 5m/15m/1h: {ar(x["t5"])} / {ar(x["t15"])} / {ar(x["t1"])}\n🕯 Price Action: {ar(x["pa"])}\n💧 Liquidity: {"Sweep BUY" if x["liq"]["buy"] else "Sweep SELL" if x["liq"]["sell"] else "لا Sweep مؤكد"}\n🟢 دعم: {x["sup"]:.2f} | 🔴 مقاومة: {x["res"]:.2f}\n🧬 Harmonic 5m: {h5}\n🧬 Harmonic 15m: {h15}\n📈 RSI: {x["s5"]["r"]:.1f} | ATR: {x["a"]:.2f}\n📰 الأخبار: {news_label} — تنبيه فقط\n📣 {x["news"]["headline"][:160]}\n⚡ الوضع: تحليل فني فقط\n\n{risk}\n🧠 التوافق: {"؛ ".join(x["why"][:7]) if x["why"] else "توافق ضعيف"}\n🧠 Adaptive learning: ON\n{status}'
def stats_text():
 h=state['history'];n=len(h);w=sum(x.get('max_tp',0)>=1 for x in h);t3=sum(x.get('max_tp',0)>=3 for x in h)
 return f'📊 سجل التعلم: {n} مغلقة | TP1+ {w} ({w/n*100:.1f}%) | TP3 {t3}' if n else '📊 سجل التعلم: لا توجد نتائج مغلقة بعد'
def open_signal(x,live=None):
 if time.time()-STARTED_AT<900:
  print('SIGNAL BLOCKED: 15-minute startup safety window')
  return False
 if state['active']:
  print('SIGNAL BLOCKED: an earlier gold signal is still active')
  return False
 bar=str(x['s5']['c'][-1].get('t'))
 if state.get('last_open_bar')==bar:
  print('SIGNAL BLOCKED: duplicate entry on the same completed 5m candle')
  return False
 if time.time()-float(state.get('last_closed_at') or 0)<900:
  print('SIGNAL BLOCKED: 15-minute cooldown after the last closed trade')
  return False
 entry=float(live['c']) if live else float(x['p'])
 drift=entry-float(x['p']);a=float(x['a'])
 adverse=(x['side']=='BUY' and drift<-.15*a) or (x['side']=='SELL' and drift>.15*a)
 if adverse or abs(drift)>.35*a:
  print(f'SIGNAL BLOCKED: live price drifted from analyzed close drift={drift:.2f} ATR={a:.2f}')
  return False
 sl_dist=abs(float(x['p'])-float(x['sl']));tp_dist=[abs(float(t)-float(x['p'])) for t in (x['tp1'],x['tp2'],x['tp3'])]
 sl=entry-sl_dist if x['side']=='BUY' else entry+sl_dist
 tps=[entry+d for d in tp_dist] if x['side']=='BUY' else [entry-d for d in tp_dist]
 sig={'id':state['next_id'],'side':x['side'],'entry':entry,'sl':sl,'tps':tps,'hit':[False]*3,'max_tp':0,'features':x['features'],'buy_pct':x['bp'],'sell_pct':x['sp'],'opened_at':time.time(),'opened_bar':bar,'opened_live_t':str((live or {}).get('t',''))};state['next_id']+=1;state['last_open_bar']=bar;state['active'].append(sig);save_state();print(f'PAPER OPEN #{sig["id"]} {sig["side"]} entry={sig["entry"]:.2f} sl={sig["sl"]:.2f} tp1={sig["tps"][0]:.2f} tp2={sig["tps"][1]:.2f} tp3={sig["tps"][2]:.2f}');return True
def close_signal(sig,result,price):
 global last
 sig['result']=result;sig['exit_price']=price;sig['closed_at']=time.time();state['last_closed_at']=sig['closed_at'];state['history'].append(sig.copy());state['history']=state['history'][-500:];state['active'].remove(sig);last=None;save_state();learn()
def track_live(c):
 if not state['active'] or not c:return
 for sig in list(state['active']):
  # On the opening candle, its recorded high/low may predate the entry.
  # Use only the live price until a new candle begins.
  same_candle=str(c.get('t',''))==str(sig.get('opened_live_t',''))
  if same_candle:
   hi=lo=float(c['c'])
  else:
   hi=float(c['h']);lo=float(c['l'])
  stop=lo<=sig['sl'] if sig['side']=='BUY' else hi>=sig['sl']
  tp3=hi>=sig['tps'][2] if sig['side']=='BUY' else lo<=sig['tps'][2]
  # If SL and TP3 are both inside the same 1m candle, ordering is unknown: record the conservative SL outcome.
  if stop and tp3:
   close_signal(sig,'SL_AMBIGUOUS',sig['sl']);trade_send(f'❌ GOLD SIGNAL #{sig["id"]} — SL HIT (نفس شمعة TP/SL)\n{stats_text()}');continue
  touch=(lambda z:hi>=z) if sig['side']=='BUY' else (lambda z:lo<=z)
  for i,t in enumerate(sig['tps']):
   if not sig['hit'][i] and touch(t):
    sig['hit'][i]=True;sig['max_tp']=max(sig['max_tp'],i+1);save_state();trade_send(f'✅ GOLD SIGNAL #{sig["id"]} — TP{i+1} HIT\n🎯 الهدف: {t:.2f}\n📈 المحقق: +{gold_pips(sig["entry"],t)} pips')
  if sig['hit'][2]:close_signal(sig,'TP3',sig['tps'][2]);trade_send(f'🏁 GOLD SIGNAL #{sig["id"]} اكتملت — TP3\n{stats_text()}');continue
  if stop:close_signal(sig,'SL_AFTER_TP'+str(sig['max_tp']) if sig['max_tp'] else 'SL',sig['sl']);trade_send(f'❌ GOLD SIGNAL #{sig["id"]} — SL HIT\n🎯 أعلى هدف: TP{sig["max_tp"]}\n{stats_text()}')
state=load_state();print('Gold learning state:',STATE_FILE,'history=',len(state['history']),'active=',len(state['active']),'weights=',state['weights'])
last=None;last_report=0;last_analysis=0
while True:
 poll_commands()
 breaking=geopolitical_news();notify_breaking(breaking)
 live=fetch_live()
 if live:
  track_live(live);print(f'LIVE XAU {live["c"]:.2f} H={live["h"]:.2f} L={live["l"]:.2f} active={len(state["active"])}')
 now=time.time()
 if now-last_analysis>=30:
  x=analyze();last_analysis=now
  if x:
   print(f'XAU {x["p"]:.2f} {x["side"]} BUY={x["bp"]}% SELL={x["sp"]}%')
   has_active=bool(state['active'])
   periodic=last_report==0 or now-last_report>=REPORT
   immediate=(not has_active) and x['side'] in ('BUY','SELL')
   opened=open_signal(x,live) if immediate else False
   if PAPER_MODE:
    if opened:
     send('🧪 صفقة تجريبية — لا تدخل بأموال حقيقية\n\n'+msg(x))
    if periodic:last_report=now
   elif periodic or opened:
    send(msg(x))
    if periodic:last_report=now
   if not state['active']:last=x['side']
 time.sleep(15)
