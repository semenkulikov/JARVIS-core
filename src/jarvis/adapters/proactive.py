"""Persistent, bounded proactive queue (calendar, training, protein, outbox files, morning briefing, schedule).

No audio, POST or Windows calls on import. Schedules use the operating system's local timezone;
personal routines are opt-in. The pure schedule rules live in jarvis.core.proactive.
"""
from __future__ import annotations

import ctypes
import datetime
import hashlib
import json
import logging
import math
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from jarvis.core import timetable as TIMETABLE
from jarvis.core import status as STATUS
from jarvis.core.phrases import Picker
from jarvis.core import text as jt
from jarvis.core.proactive import REPLIES, hm, parse_iso, quiet, wall

log = logging.getLogger("jarvis")
Config = Mapping[str, Any]


def last_input_epoch(now: float | None = None) -> float:
    """Read-only Windows GetLastInputInfo; tick subtraction handles 32-bit wrap."""
    if sys.platform != "win32": raise OSError("last_input_unavailable")

    class LII(ctypes.Structure): _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LII(); info.cbSize = ctypes.sizeof(info)
    u = ctypes.windll.user32; k = ctypes.windll.kernel32
    u.GetLastInputInfo.argtypes = [ctypes.POINTER(LII)]; u.GetLastInputInfo.restype = ctypes.c_int
    k.GetTickCount64.restype = ctypes.c_ulonglong
    if not u.GetLastInputInfo(ctypes.byref(info)): raise OSError("last_input_unavailable")
    elapsed = ((int(k.GetTickCount64()) & 0xFFFFFFFF) - info.dwTime) & 0xFFFFFFFF
    return float((time.time() if now is None else now) - elapsed / 1000)


class Manager:
    """Proactive queue state in cache/proactive_state.json; a corrupt file disables automation but is kept."""


    def __init__(self, base: str | os.PathLike[str], clock: Callable[[], float] = time.time,
                 input_reader: Callable[[float | None], float] = last_input_epoch) -> None:
        self.base=Path(base);self.path=self.base/'cache'/'proactive_state.json';self.outbox=self.base/'outbox';self.clock=clock;self.input_reader=input_reader;self.lock=threading.RLock();self.error: str | None = None;self.next_tick = 0.0;self.active: dict[str, Any] | None = None;self.morning_busy=False;self.snapshot_marker: tuple[Any, ...] | None = None
        self.schedule_busy: set[str] = set();self.picker=Picker({});self._entries: tuple[str, list[TIMETABLE.Entry]] = ('', [])
        self.state: dict[str, Any] = {'version':1,'dnd':False,'last_spoken':0,'done':{},'pending':[],'last_input':None,'morning_pending':None,'morning_date':None,'schedule':{}}
        try:
            if self.path.exists():
                d=json.loads(self.path.read_text(encoding='utf-8-sig'))
                if d.get('version')!=1 or not isinstance(d.get('done'),dict) or not isinstance(d.get('pending'),list) or not isinstance(d.get('dnd'),bool):raise ValueError('invalid_state')
                if any(not isinstance(x,dict) or not isinstance(x.get('key'),str) or not isinstance(x.get('text'),str) or not isinstance(x.get('expires'),(float,int)) or not math.isfinite(x['expires']) for x in d['pending']):raise ValueError('invalid_queue')
                if not isinstance(d.get('last_spoken',0),(float,int)) or not math.isfinite(d.get('last_spoken',0)):raise ValueError('invalid_last_spoken')
                if d.get('last_input') is not None and (not isinstance(d['last_input'],(float,int)) or not math.isfinite(d['last_input'])):raise ValueError('invalid_last_input')
                if not isinstance(d.get('schedule',{}),dict):raise ValueError('invalid_schedule')
                self.state.update(d)
        except Exception as e:self.error=type(e).__name__;log.warning('proactive state invalid (%s); preserving file; automation disabled',self.error)
    def save(self) -> None:
        if self.error:raise ValueError('proactive_state_invalid')
        self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_name(self.path.name+'.tmp');tmp.write_text(json.dumps(self.state,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,self.path)
    def set_dnd(self, on: bool) -> None:
        with self.lock:self.state['dnd']=bool(on);self.save();log.info('proactive DND=%s',bool(on))
    def can_speak(self, cfg: Config, now: float | None = None) -> bool:
        now=self.clock() if now is None else now
        return not self.error and cfg.get('proactive_enabled',True) and not self.state['dnd'] and not quiet(cfg,now)
    def _add(self, key: str, text: str, expires: float, kind: str, **extra: Any) -> None:
        if key not in self.state['done'] and not any(x['key']==key for x in self.state['pending']):
            if len(self.state['pending'])<128:self.state['pending'].append(dict(key=key,text=text,expires=expires,kind=kind,**extra))
    def _snapshot(self, cfg: Config, now: float) -> dict[str, Any] | None:
        try:
            data=json.loads((self.base/'cache'/'status.json').read_text(encoding='utf-8-sig'))
            if not isinstance(data,dict):return None
            age=now-parse_iso(data.get('updated'));skew=float(cfg.get('cache_future_skew_min',STATUS.FUTURE_SKEW_MIN))*60;age=0.0 if -skew<=age<0 else age;events=data.get('events',[]);events=events if isinstance(events,list) else [];valid=0
            for e in events[:200]:
                try:
                    if isinstance(e,dict) and e.get('title') and not e.get('all_day') and not e.get('cancelled'):parse_iso(e['start_iso']);valid+=1
                except (KeyError,ValueError,TypeError,OverflowError):pass
            marker=(data.get('updated'),len(events),valid)
            if marker!=self.snapshot_marker:
                log.info('status cache parsed updated=%s events=%d valid_timed=%d fresh=%s',data.get('updated'),len(events),valid,0<=age<float(cfg.get('proactive_cache_max_age_h',3))*3600);self.snapshot_marker=marker
            return data if 0<=age<float(cfg.get('proactive_cache_max_age_h',3))*3600 else None
        except (OSError,ValueError,TypeError):return None
    def _presence(self, cfg: Config, now: float) -> None:
        try:last=float(self.input_reader(now))
        except Exception:return
        if not math.isfinite(last) or last>now+2 or last<0:return
        prev=self.state['last_input'];self.state['last_input']=max(last,prev or 0)
        n=datetime.datetime.fromtimestamp(now);day=n.date().isoformat();minute=n.hour*60+n.minute
        if prev is not None and last-prev>=float(cfg.get('morning_idle_s',14400)) and now-last<30 and hm(cfg.get('morning_start','07:00'))<=minute<hm(cfg.get('morning_end','12:00')) and self.state['morning_date']!=day and not self.state.get('morning_pending'):
            self.state['morning_pending']={'date':day,'request_id':str(uuid.uuid4()),'presence_at':last,'idle_seconds':round(last-prev)}
    def tick(self, cfg: Config, force: bool = False) -> dict[str, Any] | None:
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
            job=self._schedule(cfg,now,day)
            morning=self.state.get('morning_pending')
            if morning and isinstance(morning,dict) and job is None:
                if morning['date']!=stamp or now>=wall(day,cfg.get('morning_end','12:00')) or morning.get('attempts',0)>=int(cfg.get('morning_max_attempts',3)):self.state['morning_pending']=None
                elif cfg.get('morning_briefing_enabled',False) and self.can_speak(cfg,now) and self.state.get('morning_date')!=stamp and not self.morning_busy and now>=morning.get('retry_at',0):
                    morning['attempts']=morning.get('attempts',0)+1;morning['retry_at']=now+max(30,float(cfg.get('morning_retry_s',120)));self.morning_busy=True
                    job=dict(morning,kind='morning_briefing',local_date=stamp,timezone=(cfg.get('timezone') or datetime.datetime.fromtimestamp(now).astimezone().tzname()),reply_mode='proactive',outbox_file='proactive-'+morning['request_id']+'.txt',expires_iso=datetime.datetime.fromtimestamp(wall(day,cfg.get('morning_end','12:00'))).astimezone().isoformat())
            self.save();return job
    # ------------------------------------------------------------ schedule
    def entries(self, cfg: Config) -> list[TIMETABLE.Entry]:
        """Parsed ``schedule`` section, re-parsed only when it changes (a bad entry warns once)."""
        raw=json.dumps(cfg.get('schedule'),ensure_ascii=False,sort_keys=True,default=str)
        if raw!=self._entries[0]:self._entries=(raw,TIMETABLE.parse(cfg))
        return self._entries[1]
    def _schedule(self, cfg: Config, now: float, today: datetime.date) -> dict[str, Any] | None:
        """Queue the due schedule entries; return a briefing request when one should go to the server."""
        days=(today-datetime.timedelta(days=1),today);job=None
        self.state['schedule']={k:v for k,v in self.state.get('schedule',{}).items() if isinstance(v,dict) and k.rsplit(':',2)[-2]>=days[0].isoformat()}
        for e in self.entries(cfg):
            for d in days:
                if not e.runs_on(d):continue
                if e.kind=='say':self._schedule_say(e,d,now)
                elif job is None:job=self._schedule_briefing(e,d,now,cfg)
                else:self._schedule_briefing(e,d,now,cfg,request=False)
        return job
    def _schedule_say(self, e: TIMETABLE.Entry, d: datetime.date, now: float) -> None:
        for n in range(e.max_repeats+1):
            if n and e.key(d,n-1) not in self.state['done']:return  # a repeat follows only a spoken first call
            due=e.at(d,n);until=e.until(d,n)
            if due<=now<until and e.key(d,n) not in self.state['done'] and not any(p['key']==e.key(d,n) for p in self.state['pending']):
                self._add(e.key(d,n),self.picker.pick({e.id:list(e.say)},e.id),until,'schedule',entry=e.id,repeat=n,
                          volume=e.volume,override_quiet=e.override_quiet)
                log.info('schedule due id=%s n=%d volume=%s override_quiet=%s',e.id,n,e.volume,e.override_quiet)
    def _schedule_briefing(self, e: TIMETABLE.Entry, d: datetime.date, now: float, cfg: Config, request: bool = True) -> dict[str, Any] | None:
        key=e.key(d);due=e.at(d);until=e.until(d)
        if key in self.state['done'] or now>=until:return None
        req=self.state['schedule'].get(key);job=None
        if req is None and now>=due-e.prefetch_min*60:
            req=self.state['schedule'][key]={'request_id':str(uuid.uuid4()),'attempts':0,'retry_at':0,'ok':False}
        if req is None:return None
        if request and not req['ok'] and key not in self.schedule_busy and now>=req['retry_at'] and req['attempts']<int(cfg.get('morning_max_attempts',3)):
            req['attempts']+=1;req['retry_at']=now+max(30,float(cfg.get('morning_retry_s',120)));self.schedule_busy.add(key)
            job=dict(TIMETABLE.day_fields(now,cfg),request_id=req['request_id'],kind='morning_briefing',trigger='schedule',schedule_key=key,
                     style=e.style,reply_mode='proactive',outbox_file='proactive-'+req['request_id']+'.txt',
                     expires_iso=datetime.datetime.fromtimestamp(until).astimezone().isoformat())
        if now>=due and not any(p['key']==key for p in self.state['pending']):
            late=now>due+TIMETABLE.GRACE_MIN*60  # Jarvis was off or the laptop slept: wait for the user to be back
            self._add(key,'',until,'schedule',entry=e.id,briefing=True,file='proactive-'+req['request_id']+'.txt',
                      deadline=now+float(cfg.get('server_down_wait_s',45)),presence_after=now if late else None)
            log.info('schedule due id=%s briefing late=%s request_ok=%s',e.id,late,req['ok'])
        return job
    def cancel_repeats(self, cfg: Config, entry_id: str | None = None) -> int:
        """Drop the pending and coming repeats of today's say entries (all, or one id); the count dropped."""
        with self.lock:
            now=self.clock();day=datetime.datetime.fromtimestamp(now).date();count=0
            for e in self.entries(cfg):
                if e.kind!='say' or (entry_id and e.id!=entry_id):continue
                for d in (day-datetime.timedelta(days=1),day):
                    for n in range(1,e.max_repeats+1):
                        if e.key(d,n) not in self.state['done']:self.state['done'][e.key(d,n)]=now;count+=1
            self.state['pending']=[p for p in self.state['pending'] if p['key'] not in self.state['done']]
            if not self.error:self.save()
            log.info('schedule repeats cancelled: %d',count);return count
    def next_at(self, cfg: Config, entry_id: str) -> float | None:
        """Epoch of the next sounding of an entry (its first call, not repeats), or None when unknown."""
        now=self.clock();day=datetime.datetime.fromtimestamp(now).date()
        for e in self.entries(cfg):
            if e.id!=entry_id:continue
            for k in range(8):
                d=day+datetime.timedelta(days=k)
                if e.runs_on(d) and e.at(d)>now:return e.at(d)
        return None
    def _held(self) -> set[str]:
        """Outbox files of briefings not yet due; a late file of a briefing already spoken is archived."""
        held=set()
        for key,req in self.state.get('schedule',{}).items():
            name='proactive-'+str(req.get('request_id'))+'.txt'
            if key not in self.state['done']:held.add(name)
            elif (self.outbox/name).exists():self._archive(self.outbox/name,'late')
        return held
    def _present(self, since: float, now: float) -> bool:
        try:last=float(self.input_reader(now))
        except Exception:return True  # no input clock: never hold the briefing forever
        return last>since
    def _briefing(self, item: dict[str, Any], cfg: Config, now: float) -> dict[str, Any] | None:
        """The briefing text from its outbox file; the fallback once the server had its time; None to wait."""
        path=self.outbox/str(item.get('file'))
        found=self._file_item(path,cfg,now) if path.exists() else None
        if found:return dict(item,text=found['text'],path=found['path'])
        if now>=float(item.get('deadline',0)):return dict(item,fallback=True)
        return None
    def morning_result(self, job: Mapping[str, Any], success: bool, cfg: Config) -> None:
        if job.get('trigger')=='schedule':
            with self.lock:
                self.schedule_busy.discard(str(job.get('schedule_key')));req=self.state.get('schedule',{}).get(job.get('schedule_key'))
                if req and req.get('request_id')==job.get('request_id'):req['ok']=bool(success);self.save()
            return
        with self.lock:
            self.morning_busy=False;pending=self.state.get('morning_pending')
            if pending and pending.get('request_id')==job.get('request_id'):
                if success or pending.get('attempts',0)>=int(cfg.get('morning_max_attempts',3)):
                    self.state['morning_date']=pending['date'];self.state['morning_pending']=None
                self.save()
    def _archive(self, path: str | Path, reason: str) -> None:
        try:
            target=self.outbox/'done';target.mkdir(parents=True,exist_ok=True);p=Path(path);os.replace(p,target/(p.name+'.'+reason))
        except OSError:log.warning('proactive archive failed (%s)',reason)
    def _file_item(self, path: Path, cfg: Config, now: float) -> dict[str, Any] | None:
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
    def take(self, cfg: Config, sleeping: bool = False) -> dict[str, Any] | None:
        """The next item to speak now, or None. Sleep, quiet hours and DND hold everything but
        ``override_quiet`` schedule entries; schedule entries skip the minimum interval."""
        with self.lock:
            now=self.clock()
            if self.error or self.active is not None or not cfg.get('proactive_enabled',True):return None
            held=self._held();files=[]
            try:files=sorted((p for p in self.outbox.glob('proactive-*.txt') if p.name not in held),key=lambda p:(p.stat().st_mtime,p.name))[:128]
            except OSError:pass
            external=[x for x in (self._file_item(p,cfg,now) for p in files) if x is not None]
            open_=self.can_speak(cfg,now) and not sleeping
            spaced=now-self.state['last_spoken']>=max(0,float(cfg.get('proactive_min_interval_s',120)))
            item=None
            for p in self.state['pending']:
                if not (p.get('override_quiet') or (open_ and (spaced or p.get('kind')=='schedule'))):continue
                if p.get('presence_after') and not self._present(float(p['presence_after']),now):continue
                ready=self._briefing(p,cfg,now) if p.get('briefing') else p
                if ready is not None:item=ready;break
            if item is None and open_ and spaced and external:item=external[0]
            if item is None:return None
            item=dict(item)
            if item.get('event_start'):
                minutes=max(1,math.ceil((item['event_start']-now)/60));label=jt.num_ru(minutes,'f')+' '+jt.plural(minutes,'минуту','минуты','минут')
                item['text']=('Через '+label+' тренировка, сэр.') if item['kind']=='training' else ('Сэр, через '+label+' начнётся: '+item.get('title','событие')+'.')
            self.active=dict(item);self.state['last_spoken']=now;self.save();log.info('proactive queued kind=%s key=%s',item['kind'],item['key']);return dict(item)
    def complete(self, item: Mapping[str, Any], interrupted: bool = False) -> None:
        with self.lock:
            self.state['done'][item['key']]=self.clock();self.state['pending']=[p for p in self.state['pending'] if p['key']!=item['key']]
            if item.get('path'):self._archive(item['path'],'stopped' if interrupted else 'spoken')
            self.active=None;self.save();log.info('proactive complete kind=%s interrupted=%s',item['kind'],interrupted)
