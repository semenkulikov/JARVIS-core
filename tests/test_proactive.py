"""Synthetic local clock/cache fixtures. Never queries real input or calendar data."""
import datetime,json,os
import pytest
from jarvis.adapters.proactive import Manager
from jarvis.core import proactive as P

def local(hour,minute=0,day=1):return datetime.datetime(2030,1,day,hour,minute).timestamp()

@pytest.mark.parametrize('hour,minute,quiet',[(22,59,False),(23,0,True),(0,0,True),(7,59,True),(8,0,False)])
def test_quiet_hours(hour,minute,quiet):assert P.quiet(P.DEFAULTS,local(hour,minute)) is quiet

@pytest.mark.parametrize('phrase,state',[('не беспокоить',True),('режим тишины',True),('можно беспокоить',False),('выключи режим тишины',False)])
def test_dnd_intent(phrase,state):assert P.intent(phrase)['enabled'] is state

def test_personal_automations_opt_in():
 for name in ('proactive_training_enabled','proactive_protein_enabled','morning_briefing_enabled'):assert P.DEFAULTS[name] is False
 assert P.DEFAULTS['proactive_training_weekdays']==[]

def test_queue_dnd_expiry_and_archive(tmp_path):
 clock=[local(10)];(tmp_path/'outbox').mkdir()
 m=Manager(tmp_path,clock=lambda:clock[0],input_reader=lambda n:n-1)
 p=tmp_path/'outbox'/'proactive-synthetic.txt'
 p.write_text('expires: '+datetime.datetime.fromtimestamp(clock[0]+600).astimezone().isoformat()+'\nТестовое объявление.',encoding='utf-8')
 os.utime(p,(clock[0]-2,clock[0]-2));m.set_dnd(True)
 assert m.take(P.DEFAULTS) is None and p.exists()
 m.set_dnd(False);item=m.take(P.DEFAULTS);assert item['text']=='Тестовое объявление.'
 m.complete(item);assert not p.exists() and (tmp_path/'outbox'/'done'/(p.name+'.spoken')).exists()
 assert Manager(tmp_path).state['dnd'] is False

def test_morning_contract_and_once_per_day(tmp_path):
 now=[local(9)];cfg=dict(P.DEFAULTS,morning_briefing_enabled=True)
 m=Manager(tmp_path,clock=lambda:now[0],input_reader=lambda n:n)
 m.state['last_input']=now[0]-18000
 job=m.tick(cfg,True)
 assert job['kind']=='morning_briefing' and job['reply_mode']=='proactive'
 assert job['outbox_file']=='proactive-'+job['request_id']+'.txt'
 assert job['idle_seconds']>=14400
 P.parse_iso(job['expires_iso']);m.morning_result(job,True,cfg)
 now[0]+=300;assert m.tick(cfg,True) is None

def test_calendar_contract_stale_and_cancelled(tmp_path):
 now=[local(10)];cfg=dict(P.DEFAULTS);m=Manager(tmp_path,clock=lambda:now[0],input_reader=lambda n:n-1)
 (tmp_path/'cache').mkdir(exist_ok=True)
 def write(cancelled=False,age=0):
  data={'updated':datetime.datetime.fromtimestamp(now[0]-age).astimezone().isoformat(),
        'events':[{'id':'synthetic','title':'Тестовое событие','start_iso':datetime.datetime.fromtimestamp(now[0]+900).astimezone().isoformat(),'all_day':False,'cancelled':cancelled}]}
  (tmp_path/'cache'/'status.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
 write();m.tick(cfg,True);assert m.state['pending'][0]['kind']=='calendar'
 write(cancelled=True);m.tick(cfg,True);assert not m.state['pending']
 write(age=10800);m.tick(cfg,True);assert not m.state['pending']

def test_configurable_training_and_protein(tmp_path):
 now=[local(12)];day=datetime.datetime.fromtimestamp(now[0]).weekday()
 cfg=dict(P.DEFAULTS,proactive_training_enabled=True,proactive_training_weekdays=[day],proactive_training_time='12:00',proactive_protein_enabled=True,proactive_protein_time='18:00')
 m=Manager(tmp_path,clock=lambda:now[0],input_reader=lambda n:n-1)
 m.tick(cfg,True);item=m.take(cfg);assert item['kind']=='training';m.complete(item)
 now[0]=local(18);data={'updated':datetime.datetime.fromtimestamp(now[0]).astimezone().isoformat(),'protein_left':80}
 (tmp_path/'cache'/'status.json').write_text(json.dumps(data),encoding='utf-8')
 m.tick(cfg,True);item=m.take(cfg);assert item['kind']=='protein';m.complete(item)
 m.tick(cfg,True);assert not m.state['pending']
