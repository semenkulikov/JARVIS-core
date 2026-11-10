"""Export-specific safety checks; fixtures contain no real user data."""
import json,threading
from pathlib import Path
import numpy as np
import pytest
from jarvis.adapters import paths as P
from jarvis.adapters import laptop
ROOT=Path(__file__).resolve().parent.parent

def test_runtime_outside_source():assert P.HOME!=P.SOURCE_DIR and P.SOURCE_DIR==ROOT/'src'

def test_missing_projects_directory(monkeypatch,tmp_path):
 missing=str(tmp_path/'missing')
 assert laptop.find_project('пример',lambda x:x,missing)==(None,0)
 assert laptop.recent_repo(missing) is None

def test_example_config_is_neutral():
 cfg=json.loads((ROOT/'config.example.json').read_text(encoding='utf-8'))
 assert cfg['webhook_url']==cfg['webhook_auth_header']==cfg['projects_dir']==''
 assert cfg['workout_days']==[]
 assert cfg['proactive_training_weekdays']==[]
 assert not cfg['proactive_training_enabled'] and not cfg['morning_briefing_enabled']

@pytest.mark.parametrize('kind,extra',[
 ('free',{}),('status',{}),('todoist_add',{'task_text':'Synthetic task'}),
 ('clipboard_translate',{'clipboard_text':'Synthetic clipboard','target_language':'ru','clipboard_truncated':False,'context_source':'clipboard'}),
 ('clipboard_summary',{'clipboard_text':'Synthetic clipboard','clipboard_truncated':False,'context_source':'clipboard'}),
 ('food_log',{'food_text':'Synthetic food entry','confirmation_policy':'chat_if_ambiguous'}),
 ('morning_briefing',{'local_date':'2030-01-01','timezone':'UTC','reply_mode':'proactive','outbox_file':'proactive-synthetic.txt','presence_at':0,'idle_seconds':18000,'expires_iso':'2030-01-01T12:00:00+00:00'})])
def test_transport_allowlist(cfg,monkeypatch,kind,extra):
 from jarvis.adapters.transport import WebhookTransport
 from jarvis.core.state import RequestLedger,Signals
 posted=[];safe=dict(cfg,webhook_url='https://example.invalid/endpoint',webhook_auth_header='dummy_fixture')
 transport=WebhookTransport(Signals(),RequestLedger())
 monkeypatch.setattr(transport,'post_retry',lambda config,payload,**kw:posted.append(payload) or 200)
 assert transport.call('synthetic','Synthetic request','test',safe,True,kind=kind,extra_payload={**extra,'request_id':'must-not-override','unexpected_private_value':'never-forward'})
 p=posted[-1];assert p['request_id']=='synthetic' and p['kind']==kind
 assert 'unexpected_private_value' not in p and 'webhook_auth_header' not in p
 assert all(p[k]==v for k,v in extra.items())

def test_sentence_streaming_without_audio(cfg,monkeypatch,tmp_path):
 import sounddevice
 from jarvis.adapters import playback as jarvis_audio
 from jarvis.adapters.tts import Voice
 from jarvis.core.state import ListenerFSM,ListenerState,Mode,Signals
 first_played=threading.Event();seen=[];plays=[]
 def synth(text,settings):
  seen.append(text)
  if len(seen)==2:assert first_played.wait(1),'First sentence was not played while the second synthesized'
  return np.zeros(16,dtype=np.float32),16000
 def silent_play(*args,**kwargs):plays.append(True);first_played.set()
 monkeypatch.setattr(sounddevice,'play',silent_play)
 monkeypatch.setattr(sounddevice,'wait',lambda:None)
 fsm=ListenerFSM(Mode.PROCESSING);voice=Voice(str(tmp_path),ListenerState(),Signals(),fsm,jarvis_audio.Player(sounddevice))
 monkeypatch.setattr(voice,'get_audio',synth)
 assert voice.say('Первая фраза. Вторая фраза.',dict(cfg,tts_gap_s=0))
 assert voice.state.last_reply=='Первая фраза. Вторая фраза.' and fsm.mode is Mode.PROCESSING and fsm.invalid==0
 assert seen==['Первая фраза.','Вторая фраза.'] and len(plays)==2
