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
 from jarvis.adapters import laptop
 from jarvis.adapters.system import SystemBackend
 from jarvis.adapters import credentials as C
 monkeypatch.setattr(urllib.request,'urlopen',forbidden)
 monkeypatch.setattr(C,'backend',lambda:None)
 for name in ('_run','mute','volume','output_volume','screenshot','close_window','clipboard','media','monitor_off','lock','shutdown','shutdown_cancel','playlist','git','disk','window_ocr','launch','close_apps','close_windows','minimize_all','screen_size','open_console','end_process','_windows'):
  monkeypatch.setattr(SystemBackend,name,forbidden)
 monkeypatch.setattr(laptop,'press',forbidden)
 import socket
 from jarvis.adapters import fatsecret
 monkeypatch.setattr(fatsecret,'urlopen',forbidden)
 monkeypatch.setattr(socket,'create_connection',forbidden)
 monkeypatch.setattr(laptop,'monitor_off',forbidden)
 monkeypatch.setattr(laptop,'battery',forbidden)
 monkeypatch.setattr(laptop,'temperature_c',forbidden)
 if hasattr(os,'startfile'):monkeypatch.setattr(os,'startfile',forbidden)
@pytest.fixture
def cfg(app,monkeypatch):
 from jarvis.core import quick as Q
 from jarvis.core import proactive as P
 from jarvis.core import dialog as D
 from jarvis.app.settings import DEFAULTS
 from jarvis.core.phrases import SMALLTALK_ALIASES
 c=copy.deepcopy(DEFAULTS)
 from jarvis.core import protocols as PR
 c['aliases']=c['aliases']+copy.deepcopy(SMALLTALK_ALIASES)+PR.aliases(c)
 c['stress_dict']=dict(dict(P.STRESS,**Q.STRESS,**D.STRESS),**(c.get('stress_dict') or {}))
 c['followup_enabled']=False
 monkeypatch.setattr(app.c.config,'load',lambda:c)
 return c
