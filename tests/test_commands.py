"""Synthetic commands; every desktop operation is a fake backend call."""
import copy
from pathlib import Path
import pytest
import jarvis_commands as Q

class FakeBackend:
 is_fake=True
 def __init__(self):self.calls=[]
 def __getattr__(self,name):
  def call(*args):
   self.calls.append((name,args))
   if name=='clipboard':return 'Synthetic example',False
   if name=='disk':return 20*1024**3,100*1024**3,'C'
   if name=='git':return 'Тестовый коммит abc123.'
   if name=='shutdown_cancel':return True
  return call

@pytest.fixture
def harness(tmp_path,cfg):
 backend=FakeBackend();clock=[100.];c=Q.Controller(tmp_path,backend,lambda:clock[0]);said=[];posted=[]
 def say(text,settings,**kwargs):said.append((text,settings,kwargs));return True
 def forward(text,**kwargs):posted.append((text,kwargs))
 def execute(text,**kwargs):
  alias=Q.match(text,cfg);assert alias
  return c.execute(alias,text,cfg,say,forward,test=True,**kwargs)
 return c,backend,clock,said,posted,execute

@pytest.mark.parametrize('text,seconds',[
 ('пять минут',300),('один час тридцать минут',5400),('полторы минуты',90),
 ('1,5 минуты',90),('полчаса',1800),('тридцать секунд',30),('час',3600),('-2 минуты',None)])
def test_duration(text,seconds):assert Q.duration(text)==seconds

@pytest.mark.parametrize('text,method',[
 ('сделай скриншот','screenshot'),('закрой окно','close_window'),
 ('сколько свободно на диске','disk'),('последний коммит проекта пример','git'),
 ('прочитай буфер','clipboard')])
def test_actions_mocked(harness,text,method):
 _,b,_,_,_,execute=harness;execute(text);assert b.calls[-1][0]==method

def test_mute_is_set_state(harness):
 _,b,_,_,_,execute=harness
 execute('выключи звук');execute('выключи звук');execute('включи звук')
 assert b.calls==[('mute',(True,)),('mute',(True,)),('mute',(False,))]

@pytest.mark.parametrize('text,expected',[('громкость на тридцать',30.),('громкость на сто',100.),('громкость на ноль',0.)])
def test_volume(harness,text,expected):
 _,b,_,_,_,execute=harness;execute(text);assert b.calls[-1]==('volume',(expected,))

def test_invalid_volume_cannot_act(harness):
 _,b,_,_,_,execute=harness;execute('громкость на сто двадцать');assert not b.calls

@pytest.mark.parametrize('trigger,conf,delay,approved',[
 ('wake_word',1.,0,False),('followup',.3,0,False),('followup',1.,11,False),('followup',.99,0,True)])
def test_shutdown_confirmation_gate(harness,trigger,conf,delay,approved):
 c,b,clock,_,_,execute=harness;execute('выключи через десять минут')
 assert not any(x[0]=='shutdown' for x in b.calls)
 clock[0]+=delay;answer=c.confirmation('да',trigger,conf)
 assert answer['approved'] is approved

@pytest.mark.parametrize('answer',['нет','не надо','отмена','отмени'])
def test_decline_shutdown(harness,answer):
 c,b,_,_,_,execute=harness;execute('выключи через десять минут')
 assert c.confirmation(answer,'followup',1.)['approved'] is False
 assert not b.calls

def test_shutdown_only_after_confirm_and_cancel(harness,cfg):
 c,b,_,_,_,execute=harness;execute('выключи через десять минут')
 result=c.confirmation('подтверждаю','followup',1.)
 c.execute({'cmd':'shutdown_confirm',**result},'',cfg,lambda *a,**kw:True,lambda *a,**kw:None,test=True)
 assert b.calls[-1]==('shutdown',(600,))
 execute('отмени выключение');assert b.calls[-1]==('shutdown_cancel',())

@pytest.mark.parametrize('text,kind,field,value',[
 ('добавь задачу проверить пример','todoist_add','task_text','проверить пример'),
 ('переведи буфер на английский','clipboard_translate','target_language','en'),
 ('кратко перескажи буфер','clipboard_summary','clipboard_text','Synthetic example'),
 ('добавь двести грамм творога','food_log','confirmation_policy','chat_if_ambiguous')])
def test_payload_contracts(harness,text,kind,field,value):
 _,_,_,_,posted,execute=harness;execute(text)
 assert posted[-1][1]['kind']==kind
 assert posted[-1][1]['extra_payload'][field]==value

def test_persistent_timers_and_notes(harness,tmp_path):
 c,_,_,_,_,execute=harness
 execute('таймер на пять минут');execute('каждые сорок пять минут напоминай встать')
 records=Q.PersistentTimers(tmp_path/'cache'/'timers.json').items
 assert len(records)==2 and any(r['interval']==2700 for r in records)
 execute('запиши идею синтетическая проверка')
 assert 'синтетическая проверка' in (tmp_path/'notes.md').read_text(encoding='utf-8')
 execute('отмени таймер');assert all(r['kind']=='reminder' for r in c.timers.items)
 execute('отмени напоминания');assert not c.timers.items

@pytest.mark.parametrize('text,rate',[('повтори','fast'),('помедленнее','slow')])
def test_repeat_complete_reply(harness,text,rate):
 _,_,_,said,_,execute=harness;execute(text,last_reply='Первая часть. Вторая часть.')
 assert said[-1][0]=='Первая часть. Вторая часть.'
 assert said[-1][1]['silero_rate']==rate

def test_modes_do_not_duplicate_owned_timers(harness):
 c,b,_,_,_,execute=harness
 execute('таймер на пять минут');execute('режим тренировки');execute('режим тренировки')
 assert len(c.timers.items)==3
 execute('режим фокуса');assert len(c.timers.items)==2
 execute('режим сна');assert len(c.timers.items)==1 and b.calls[-1][0]=='lock'
