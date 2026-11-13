from jarvis.core import matching as M
import time,pytest
from jarvis.core import routing as ROUTING
from jarvis.app import server_jobs as CONV
from jarvis.core.state import ServerJob
class Sig:
 def clear(self):pass
 def wait(self,cfg):time.sleep(0.01)
@pytest.fixture
def outbox(app,cfg,monkeypatch,tmp_path):
 from jarvis.adapters.outbox import Outbox
 monkeypatch.setattr(app.c, "outbox",Outbox(str(tmp_path),done=str(tmp_path/'done'),signal=Sig()));app.c.outbox.ensure()
 monkeypatch.setattr(app.c.jobs, "outbox",app.c.outbox)
 app.c.signals.interrupt.clear();app.c.ledger.down_since=None
 cfg.update(reply_timeout_s=0.4,server_notice_s=0.1,server_down_wait_s=0.1,server_down_ttl_s=60)
 said=[]
 def wait(rid):
  job=ServerJob(rid=rid,text='вопрос',kind='free',created=time.time(),listener_ack='Сейчас, сэр.');ok=app.c.jobs.wait(job,cfg)
  while (p:=job.pop(time.time())) is not None:said.append(p.text)
  return ok
 app.wait=wait
 return said
def test_no_server_file_says_server_down_and_marks(app,cfg,outbox):
 assert app.wait('r1') is False
 assert outbox==[CONV.SERVER_SLOW_PHRASE,CONV.SERVER_DOWN_PHRASE]
 assert app.c.ledger.down_since is not None and app.c.ledger.is_cancelled('r1')
def test_second_request_fails_fast_when_down(app,cfg,outbox):
 app.c.ledger.down_since=time.time();t=time.time()
 assert app.wait('r2') is False
 assert time.time()-t<0.35 and outbox==[CONV.SERVER_DOWN_PHRASE]
def test_reply_clears_down_flag(app,cfg,outbox,tmp_path):
 app.c.ledger.down_since=time.time()
 (tmp_path/'r3.txt').write_text('Готово, сэр.',encoding='utf-8')
 assert app.wait('r3') is True
 assert app.c.ledger.down_since is None and outbox==['Готово, сэр.']
def test_down_flag_expires(app,cfg):
 app.c.ledger.down_since=time.time()-120;cfg['server_down_ttl_s']=60
 assert not app.c.ledger.recently_down(cfg)
@pytest.mark.parametrize('text',['сэр','да сэр','сэр да','ну сэр'])
def test_filler_not_sent(app,cfg,text):
 assert M.filler_only(text);assert app.c.router.choose(text,1.0,'курсор',cfg)==('',False)
@pytest.mark.parametrize('text',['да','статус','сэр который час','да выключи'])
def test_not_filler(text):assert not M.filler_only(text)
@pytest.mark.parametrize('text',['все','всё','это всё','на этом всё'])
def test_vse_is_local(app,cfg,text):
 al=ROUTING.match_alias(text,cfg);assert al and al['action']=='smalltalk' and al['name']=='chat_done'
@pytest.mark.parametrize('text',['все хорошо','всё нормально'])
def test_vse_khorosho_still_okay(app,cfg,text):
 al=ROUTING.match_alias(text,cfg);assert al and al['name']=='chat_okay'
@pytest.mark.parametrize('text,action',[('который час','time'),('громче','key'),('тише','key'),('без звука','key'),('поставь таймер на пять минут','timer'),('повтори','quick2'),('ты здесь','smalltalk'),('открой браузер','open'),('заряд','battery')])
def test_quick_commands_local(app,cfg,text,action):
 al=ROUTING.match_alias(text,cfg);assert al and al['action']!='webhook' and al['action'] in (action,'quick2')
