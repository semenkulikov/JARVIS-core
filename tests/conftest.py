"""Model-free tests: fail closed on real audio, HTTP or desktop actions."""
import copy,os,sys,types,urllib.request
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
SD=types.ModuleType('sounddevice')
def forbidden(*a,**kw):raise AssertionError('REAL AUDIO/NETWORK/SYSTEM ACTION FORBIDDEN')
SD.play=forbidden;SD.wait=lambda:None;SD.stop=lambda:None;SD.InputStream=forbidden
sys.modules['sounddevice']=SD
@pytest.fixture
def app(tmp_path):
 """A fresh listener wired by the composition root against an empty JARVIS_HOME."""
 from jarvis.app.context import build_app
 return build_app(tmp_path/'home',sd=SD)
@pytest.fixture(autouse=True)
def guards(monkeypatch):
 import jarvis_credentials as C,jarvis_commands as Q,laptop
 monkeypatch.setattr(urllib.request,'urlopen',forbidden)
 monkeypatch.setattr(C,'backend',lambda:None)
 for name in ('_run','mute','volume','screenshot','close_window','clipboard','media','monitor_off','lock','shutdown','shutdown_cancel','playlist','git','disk','window_ocr'):
  monkeypatch.setattr(Q.SystemBackend,name,forbidden)
 monkeypatch.setattr(laptop,'press',forbidden)
 import fatsecret_call,socket
 monkeypatch.setattr(fatsecret_call,'call',forbidden)
 monkeypatch.setattr(socket,'create_connection',forbidden)
 monkeypatch.setattr(laptop,'monitor_off',forbidden)
 monkeypatch.setattr(laptop,'battery',forbidden)
 monkeypatch.setattr(laptop,'temperature_c',forbidden)
 if hasattr(os,'startfile'):monkeypatch.setattr(os,'startfile',forbidden)
@pytest.fixture
def cfg(app,monkeypatch):
 import jarvis_commands as Q, jarvis_proactive as P
 from jarvis.core import dialog as D
 from jarvis.app.settings import DEFAULTS
 from jarvis.core.phrases import SMALLTALK_ALIASES
 c=copy.deepcopy(DEFAULTS)
 c['aliases']=c['aliases']+copy.deepcopy(SMALLTALK_ALIASES)
 c['stress_dict']=dict(dict(P.STRESS,**Q.STRESS,**D.STRESS),**(c.get('stress_dict') or {}))
 c['followup_enabled']=False
 monkeypatch.setattr(app.c.config,'load',lambda:c)
 return c
