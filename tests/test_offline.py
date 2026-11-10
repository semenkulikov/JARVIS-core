from jarvis.core import matching as M
import time,pytest
from jarvis.core import routing as ROUTING
class Sig:
 def clear(self):pass
 def wait(self,cfg):time.sleep(0.01)
@pytest.fixture
def outbox(listener,cfg,monkeypatch,tmp_path):
 said=[];monkeypatch.setattr(listener,'OUTBOX',str(tmp_path));monkeypatch.setattr(listener,'OUTBOX_SIGNAL',Sig())
 monkeypatch.setattr(listener,'say',lambda t,c,**k:said.append(t));monkeypatch.setattr(listener,'say_reply',lambda t,c,**k:said.append(t))
 listener.interrupt.clear();listener.LEDGER.down_since=None
 cfg.update(reply_timeout_s=0.4,server_notice_s=0.1,server_down_wait_s=0.1,server_down_ttl_s=60)
 return said
def test_no_server_file_says_server_down_and_marks(listener,cfg,outbox):
 assert listener.wait_replies('r1',cfg,listener_ack='Сейчас, сэр.') is False
 assert outbox==[listener.SERVER_SLOW_PHRASE,listener.SERVER_DOWN_PHRASE]
 assert listener.LEDGER.down_since is not None and listener.LEDGER.is_cancelled('r1')
def test_second_request_fails_fast_when_down(listener,cfg,outbox):
 listener.LEDGER.down_since=time.time();t=time.time()
 assert listener.wait_replies('r2',cfg,listener_ack='Сейчас, сэр.') is False
 assert time.time()-t<0.35 and outbox==[listener.SERVER_DOWN_PHRASE]
def test_reply_clears_down_flag(listener,cfg,outbox,tmp_path):
 listener.LEDGER.down_since=time.time()
 (tmp_path/'r3.txt').write_text('Готово, сэр.',encoding='utf-8')
 assert listener.wait_replies('r3',cfg,listener_ack='Сейчас, сэр.') is True
 assert listener.LEDGER.down_since is None and outbox==['Готово, сэр.']
def test_down_flag_expires(listener,cfg):
 listener.LEDGER.down_since=time.time()-120;cfg['server_down_ttl_s']=60
 assert not listener.LEDGER.recently_down(cfg)
@pytest.mark.parametrize('text',['сэр','да сэр','сэр да','ну сэр'])
def test_filler_not_sent(listener,cfg,text):
 assert M.filler_only(text);assert listener.choose(text,1.0,'курсор',cfg)==('',False)
@pytest.mark.parametrize('text',['да','статус','сэр который час','да выключи'])
def test_not_filler(text):assert not M.filler_only(text)
@pytest.mark.parametrize('text',['все','всё','это всё','на этом всё'])
def test_vse_is_local(listener,cfg,text):
 al=ROUTING.match_alias(text,cfg);assert al and al['action']=='smalltalk' and al['name']=='chat_done'
@pytest.mark.parametrize('text',['все хорошо','всё нормально'])
def test_vse_khorosho_still_okay(listener,cfg,text):
 al=ROUTING.match_alias(text,cfg);assert al and al['name']=='chat_okay'
@pytest.mark.parametrize('text,action',[('который час','time'),('громче','key'),('тише','key'),('без звука','key'),('поставь таймер на пять минут','timer'),('повтори','quick2'),('ты здесь','smalltalk'),('открой браузер','open'),('заряд','battery')])
def test_quick_commands_local(listener,cfg,text,action):
 al=ROUTING.match_alias(text,cfg);assert al and al['action']!='webhook' and al['action'] in (action,'quick2')
