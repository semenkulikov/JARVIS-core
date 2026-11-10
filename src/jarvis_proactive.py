"""Persistent, bounded proactive queue. No audio, POST or Windows calls on import.
Schedules use the operating system's local timezone; personal routines are opt-in.
"""
import ctypes,datetime,hashlib,json,logging,math,os,re,threading,time,uuid
from pathlib import Path
log=logging.getLogger('jarvis')
DEFAULTS={'proactive_enabled':True,'proactive_quiet_start':'23:00','proactive_quiet_end':'08:00','proactive_min_interval_s':120,'proactive_tick_s':5,'proactive_max_chars':4000,'proactive_training_enabled':False,'proactive_training_time':'12:00','proactive_training_weekdays':[],'proactive_calendar_enabled':True,'proactive_calendar_lead_min':15,'proactive_cache_max_age_h':3,'proactive_protein_enabled':False,'proactive_protein_time':'18:00','proactive_protein_expire_time':'22:00','proactive_protein_left_g':60,'morning_briefing_enabled':False,'morning_start':'07:00','morning_end':'12:00','morning_idle_s':14400,'morning_retry_s':120,'morning_max_attempts':3,'priority_wake_min_conf':.85,'timezone':''}
PHRASES=['не беспокоить','режим тишины','включи режим тишины','можно беспокоить','выключи режим тишины']
REPLIES=['Не беспокою, сэр.','Уведомления включены, сэр.','Через пятнадцать минут тренировка, сэр.','Сэр, до нормы белка осталось больше шестидесяти граммов. Не забудьте про ужин.']
STRESS={w.replace('+',''):w for w in ['б+ольше','ч+ерез','беспок+ою','уведомл+ения','включен+ы','тренир+овка','пятн+адцать','шест+идесяти','гр+аммов','заб+удьте','+ужин','начн+ется','соб+ытие']}
def intent(text):
 t=' '.join(re.findall(r'\w+',text.lower().replace('ё','е')))
 if t in PHRASES:return {'name':'dnd_on' if t in PHRASES[:3] else 'dnd_off','action':'proactive_dnd','enabled':t in PHRASES[:3]}
 return None

def parse_iso(value):
 if not isinstance(value,str):raise ValueError('ISO_expected')
 d=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
 if d.tzinfo is None:raise ValueError('ISO_timezone_required')
 return d.timestamp()
def hm(value):
 if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise ValueError('invalid_hhmm')
 h,m=map(int,value.split(':'));return h*60+m
def wall(day,value):
 # Naive local time .timestamp() uses historical Windows DST, unlike today's fixed UTC offset.
 return datetime.datetime.combine(day,datetime.time(*map(int,value.split(':')))).timestamp()
def quiet(cfg,epoch):
 n=datetime.datetime.fromtimestamp(epoch);t=n.hour*60+n.minute;a=hm(cfg.get('proactive_quiet_start','23:00'));b=hm(cfg.get('proactive_quiet_end','08:00'))
 return a<=t<b if a<b else (t>=a or t<b) if a>b else False

def last_input_epoch(now=None):
 """Read-only Windows GetLastInputInfo; tick subtraction handles 32-bit wrap."""
 class LII(ctypes.Structure):_fields_=[('cbSize',ctypes.c_uint),('dwTime',ctypes.c_uint)]
 info=LII();info.cbSize=ctypes.sizeof(info)
 u=ctypes.windll.user32;k=ctypes.windll.kernel32
 u.GetLastInputInfo.argtypes=[ctypes.POINTER(LII)];u.GetLastInputInfo.restype=ctypes.c_int
 k.GetTickCount64.restype=ctypes.c_ulonglong
 if not u.GetLastInputInfo(ctypes.byref(info)):raise OSError('last_input_unavailable')
 elapsed=((int(k.GetTickCount64())&0xFFFFFFFF)-info.dwTime)&0xFFFFFFFF
 return (time.time() if now is None else now)-elapsed/1000

class Manager:
 def __init__(self,base,clock=time.time,input_reader=last_input_epoch):
  self.base=Path(base);self.path=self.base/'cache'/'proactive_state.json';self.outbox=self.base/'outbox';self.clock=clock;self.input_reader=input_reader;self.lock=threading.RLock();self.error=None;self.next_tick=0;self.active=None;self.morning_busy=False;self.snapshot_marker=None
  self.state={'version':1,'dnd':False,'last_spoken':0,'done':{},'pending':[],'last_input':None,'morning_pending':None,'morning_date':None}
  try:
   if self.path.exists():
    d=json.loads(self.path.read_text(encoding='utf-8-sig'))
    if d.get('version')!=1 or not isinstance(d.get('done'),dict) or not isinstance(d.get('pending'),list) or not isinstance(d.get('dnd'),bool):raise ValueError('invalid_state')
    if any(not isinstance(x,dict) or not isinstance(x.get('key'),str) or not isinstance(x.get('text'),str) or not isinstance(x.get('expires'),(float,int)) or not math.isfinite(x['expires']) for x in d['pending']):raise ValueError('invalid_queue')
    if not isinstance(d.get('last_spoken',0),(float,int)) or not math.isfinite(d.get('last_spoken',0)):raise ValueError('invalid_last_spoken')
    if d.get('last_input') is not None and (not isinstance(d['last_input'],(float,int)) or not math.isfinite(d['last_input'])):raise ValueError('invalid_last_input')
    self.state.update(d)
  except Exception as e:self.error=type(e).__name__;log.warning('proactive state invalid (%s); preserving file; automation disabled',self.error)
 def save(self):
  if self.error:raise ValueError('proactive_state_invalid')
  self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_name(self.path.name+'.tmp');tmp.write_text(json.dumps(self.state,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,self.path)
 def set_dnd(self,on):
  with self.lock:self.state['dnd']=bool(on);self.save();log.info('proactive DND=%s',bool(on))
 def can_speak(self,cfg,now=None):
  now=self.clock() if now is None else now
  return not self.error and cfg.get('proactive_enabled',True) and not self.state['dnd'] and not quiet(cfg,now)
 def _add(self,key,text,expires,kind,**extra):
  if key not in self.state['done'] and not any(x['key']==key for x in self.state['pending']):
   if len(self.state['pending'])<128:self.state['pending'].append(dict(key=key,text=text,expires=expires,kind=kind,**extra))
 def _snapshot(self,cfg,now):
  try:
   data=json.loads((self.base/'cache'/'status.json').read_text(encoding='utf-8-sig'))
   if not isinstance(data,dict):return None
   age=now-parse_iso(data.get('updated'));events=data.get('events',[]);events=events if isinstance(events,list) else [];valid=0
   for e in events[:200]:
    try:
     if isinstance(e,dict) and e.get('title') and not e.get('all_day') and not e.get('cancelled'):parse_iso(e['start_iso']);valid+=1
    except (KeyError,ValueError,TypeError,OverflowError):pass
   marker=(data.get('updated'),len(events),valid)
   if marker!=self.snapshot_marker:
    log.info('status cache parsed updated=%s events=%d valid_timed=%d fresh=%s',data.get('updated'),len(events),valid,0<=age<float(cfg.get('proactive_cache_max_age_h',3))*3600);self.snapshot_marker=marker
   return data if 0<=age<float(cfg.get('proactive_cache_max_age_h',3))*3600 else None
  except (OSError,ValueError,TypeError):return None
 def _presence(self,cfg,now):
  try:last=float(self.input_reader(now))
  except Exception:return
  if not math.isfinite(last) or last>now+2 or last<0:return
  prev=self.state['last_input'];self.state['last_input']=max(last,prev or 0)
  n=datetime.datetime.fromtimestamp(now);day=n.date().isoformat();minute=n.hour*60+n.minute
  if prev is not None and last-prev>=float(cfg.get('morning_idle_s',14400)) and now-last<30 and hm(cfg.get('morning_start','07:00'))<=minute<hm(cfg.get('morning_end','12:00')) and self.state['morning_date']!=day and not self.state.get('morning_pending'):
   self.state['morning_pending']={'date':day,'request_id':str(uuid.uuid4()),'presence_at':last,'idle_seconds':round(last-prev)}
 def tick(self,cfg,force=False):
  with self.lock:
   now=self.clock()
   if self.error or (not force and now<self.next_tick):return None
   self.next_tick=now+max(1,float(cfg.get('proactive_tick_s',5)))
   if not cfg.get('proactive_enabled',True):return None
   if cfg.get('morning_briefing_enabled',False):self._presence(cfg,now)
   day=datetime.datetime.fromtimestamp(now).date();stamp=day.isoformat();snap=self._snapshot(cfg,now)
   self.state['done']={k:v for k,v in self.state['done'].items() if isinstance(v,(float,int)) and now-v<7*86400}
   self.state['pending']=[p for p in self.state['pending'] if isinstance(p,dict) and isinstance(p.get('expires'),(float,int)) and p['expires']>now]
   if cfg.get('proactive_training_enabled',False) and day.weekday() in cfg.get('proactive_training_weekdays',[]):
    due=wall(day,cfg.get('proactive_training_time','12:00'));expires=due+15*60
    if due<=now<expires:self._add('training:'+stamp,REPLIES[2],expires,'training',event_start=expires)
   self.state['pending']=[p for p in self.state['pending'] if cfg.get('proactive_'+p.get('kind','')+'_enabled',True)]
   allowed_events=set()
   if snap is not None and cfg.get('proactive_calendar_enabled',True):
    events=snap.get('events',[])
    if not isinstance(events,list):events=[]
    for e in events[:200]:
     try:
      if not isinstance(e,dict) or e.get('all_day') or e.get('cancelled'):continue
      start=parse_iso(e['start_iso']);title=' '.join(str(e['title']).split())[:180]
      if not title:continue
      key='calendar:'+hashlib.sha256((str(e.get('id') or title)+'|'+str(start)).encode()).hexdigest()[:24];allowed_events.add(key)
      if start-float(cfg.get('proactive_calendar_lead_min',15))*60<=now<start:self._add(key,'Сэр, скоро начнётся: '+title+'.',start,'calendar',event_start=start,title=title)
     except (KeyError,ValueError,TypeError,OverflowError):continue
   # Drop cancelled/moved/stale event announcements before delivery, never read obsolete reminders.
   self.state['pending']=[p for p in self.state['pending'] if p.get('kind')!='calendar' or p['key'] in allowed_events]
   if snap is not None and cfg.get('proactive_protein_enabled',False):
    try:left=float(snap['protein_left'])
    except (KeyError,ValueError,TypeError):left=0
    due=wall(day,cfg.get('proactive_protein_time','18:00'));end=wall(day,cfg.get('proactive_protein_expire_time','22:00'))
    if due<=now<end and math.isfinite(left) and left>float(cfg.get('proactive_protein_left_g',60)):self._add('protein:'+stamp,REPLIES[3],end,'protein')
    if not math.isfinite(left) or left<=float(cfg.get('proactive_protein_left_g',60)):self.state['pending']=[p for p in self.state['pending'] if p.get('kind')!='protein']
   else:self.state['pending']=[p for p in self.state['pending'] if p.get('kind')!='protein']
   morning=self.state.get('morning_pending');job=None
   if morning and isinstance(morning,dict):
    if morning['date']!=stamp or now>=wall(day,cfg.get('morning_end','12:00')) or morning.get('attempts',0)>=int(cfg.get('morning_max_attempts',3)):self.state['morning_pending']=None
    elif cfg.get('morning_briefing_enabled',False) and self.can_speak(cfg,now) and self.state.get('morning_date')!=stamp and not self.morning_busy and now>=morning.get('retry_at',0):
     morning['attempts']=morning.get('attempts',0)+1;morning['retry_at']=now+max(30,float(cfg.get('morning_retry_s',120)));self.morning_busy=True
     job=dict(morning,kind='morning_briefing',local_date=stamp,timezone=(cfg.get('timezone') or datetime.datetime.fromtimestamp(now).astimezone().tzname()),reply_mode='proactive',outbox_file='proactive-'+morning['request_id']+'.txt',expires_iso=datetime.datetime.fromtimestamp(wall(day,cfg.get('morning_end','12:00'))).astimezone().isoformat())
   self.save();return job
 def morning_result(self,job,success,cfg):
  with self.lock:
   self.morning_busy=False;pending=self.state.get('morning_pending')
   if pending and pending.get('request_id')==job.get('request_id'):
    if success or pending.get('attempts',0)>=int(cfg.get('morning_max_attempts',3)):
     self.state['morning_date']=pending['date'];self.state['morning_pending']=None
    self.save()
 def _archive(self,path,reason):
  try:
   target=self.outbox/'done';target.mkdir(parents=True,exist_ok=True);p=Path(path);os.replace(p,target/(p.name+'.'+reason))
  except OSError:log.warning('proactive archive failed (%s)',reason)
 def _file_item(self,path,cfg,now):
  try:
   if path.stat().st_size>int(cfg.get('proactive_max_chars',4000))*4+200:self._archive(path,'oversize');return None
   if now-path.stat().st_mtime<.25:return None
   before=path.stat();text=path.read_text(encoding='utf-8-sig').strip();after=path.stat()
   if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):return None
   expires=None
   if text.lower().startswith('expires:'):
    line,sep,text=text.partition('\n')
    try:expires=parse_iso(line.split(':',1)[1].strip())
    except (ValueError,TypeError):self._archive(path,'bad_expiry');return None
   if expires is not None and now>=expires:self._archive(path,'expired');return None
   if not text.strip():return None # writer may still be filling it; atomic rename recommended
   if len(text)>int(cfg.get('proactive_max_chars',4000)):self._archive(path,'oversize');return None
   key='file:'+path.name
   if key in self.state['done']:self._archive(path,'duplicate');return None
   return {'key':key,'text':text.strip(),'expires':expires,'kind':'file','path':str(path)}
  except (OSError,UnicodeError):return None
 def take(self,cfg):
  with self.lock:
   now=self.clock()
   if self.error or self.active is not None:return None
   files=[]
   try:files=sorted(self.outbox.glob('proactive-*.txt'),key=lambda p:(p.stat().st_mtime,p.name))[:128]
   except OSError:pass
   external=[x for x in (self._file_item(p,cfg,now) for p in files) if x is not None]
   if not self.can_speak(cfg,now) or now-self.state['last_spoken']<max(0,float(cfg.get('proactive_min_interval_s',120))):return None
   pending=self.state['pending'];item=pending[0] if pending else external[0] if external else None
   if item is None:return None
   item=dict(item)
   if item.get('event_start'):
    from jarvis.core import text as jt
    minutes=max(1,math.ceil((item['event_start']-now)/60));label=jt.num_ru(minutes,'f')+' '+jt.plural(minutes,'минуту','минуты','минут')
    item['text']=('Через '+label+' тренировка, сэр.') if item['kind']=='training' else ('Сэр, через '+label+' начнётся: '+item.get('title','событие')+'.')
   self.active=dict(item);self.state['last_spoken']=now;self.save();log.info('proactive queued kind=%s key=%s',item['kind'],item['key']);return dict(item)
 def complete(self,item,interrupted=False):
  with self.lock:
   self.state['done'][item['key']]=self.clock();self.state['pending']=[p for p in self.state['pending'] if p['key']!=item['key']]
   if item.get('path'):self._archive(item['path'],'stopped' if interrupted else 'spoken')
   self.active=None;self.save();log.info('proactive complete kind=%s interrupted=%s',item['kind'],interrupted)

def priority_candidate(text,confidence,speaker_text,cfg):
 """Require an actual leading wake name, not just a grammar hallucination or TTS echo."""
 words=re.findall(r'\w+',text.lower().replace('ё','е'));said=re.findall(r'\w+',speaker_text.lower().replace('ё','е'))
 allowed={'джарвис','жарвис','джервис','дарвис','гарвис','джарви','джави','jarvis'}
 wake=next((i for i,w in enumerate(words[:3]) if w in allowed),None)
 if wake is None or confidence<float(cfg.get('priority_wake_min_conf',.85)):return False
 if any(w in allowed for w in said):return False
 return wake==0 or all(w in ('эй','хей','хэй','слушай','ну') for w in words[:wake])
