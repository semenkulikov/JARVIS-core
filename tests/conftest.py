"""Model-free tests: fail closed on real audio, HTTP or desktop actions."""
import copy,logging,os,sys,tempfile,types,urllib.request
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
SD=types.ModuleType('sounddevice')
def forbidden(*a,**kw):raise AssertionError('REAL AUDIO/NETWORK/SYSTEM ACTION FORBIDDEN')
SD.play=forbidden;SD.wait=lambda:None;SD.stop=lambda:None;SD.InputStream=forbidden
sys.modules['sounddevice']=SD
@pytest.fixture(scope='session')
def listener():
 with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
  import jarvis_paths
  old=jarvis_paths.HOME;jarvis_paths.HOME=Path(d)
  try:
   src=(ROOT/'src'/'jarvis_voice.py').read_text(encoding='utf-8')
   m=types.ModuleType('jarvis_pytest_silent');m.__file__=str(ROOT/'src'/'jarvis_voice.py')
   sys.modules[m.__name__]=m;exec(compile(src,m.__file__,'exec'),m.__dict__)
   yield m
  finally:
   logging.shutdown();jarvis_paths.HOME=old
@pytest.fixture(autouse=True)
def guards(monkeypatch):
 import jarvis_credentials as C,jarvis_commands as Q,laptop
 monkeypatch.setattr(urllib.request,'urlopen',forbidden)
 monkeypatch.setattr(C,'backend',lambda:None)
 for name in ('_run','mute','volume','screenshot','close_window','clipboard','media','monitor_off','lock','shutdown','shutdown_cancel','playlist','git','disk','window_ocr'):
  monkeypatch.setattr(Q.SystemBackend,name,forbidden)
 monkeypatch.setattr(laptop,'press',forbidden)
 import socket
 monkeypatch.setattr(socket,'create_connection',forbidden)
 monkeypatch.setattr(laptop,'monitor_off',forbidden)
 monkeypatch.setattr(laptop,'battery',forbidden)
 monkeypatch.setattr(laptop,'temperature_c',forbidden)
 if hasattr(os,'startfile'):monkeypatch.setattr(os,'startfile',forbidden)
@pytest.fixture
def cfg(listener,monkeypatch):
 c=copy.deepcopy(listener.DEFAULTS)
 c['aliases']=c['aliases']+copy.deepcopy(listener.SMALLTALK_ALIASES)
 c['stress_dict']=dict(dict(listener.PROACTIVE.STRESS,**listener.QUICK.STRESS),**(c.get('stress_dict') or {}))
 c['followup_enabled']=False
 monkeypatch.setattr(listener,'load_cfg',lambda:c)
 return c
