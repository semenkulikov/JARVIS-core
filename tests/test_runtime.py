import pytest
from jarvis.adapters import runtime as R
from jarvis.app import supervisor as S
@pytest.mark.parametrize('n,expected',[(0,2),(1,2),(2,4),(3,8),(4,16),(5,32),(6,64),(7,128),(8,256),(9,300),(20,300),(100000,300)])
def test_backoff(n,expected):assert R.crash_delay(n)==expected

def test_intentional_marker(tmp_path):
 R.mark_stop(tmp_path);assert R.stop_marker(tmp_path).exists();(tmp_path/'stop').touch();R.clear_stop(tmp_path);assert not R.stop_marker(tmp_path).exists() and not (tmp_path/'stop').exists()

def test_crash_restarts_with_delay(tmp_path):
 clock=[0.];launch=[]
 class Dead:
  pid=99
  def poll(self):return 1
 def spawn():launch.append(clock[0]);return Dead()
 S.run(tmp_path,spawn=spawn,sleep=lambda sec:clock.__setitem__(0,clock[0]+sec),clock=lambda:clock[0],alive=lambda:False,limit=80)
 assert len(launch)>=4
 assert all(launch[i+1]-launch[i]>=R.crash_delay(i+1) for i in range(len(launch)-1))

def test_no_duplicate_adopt_existing(tmp_path):
 launches=[];S.run(tmp_path,spawn=lambda:launches.append(1),sleep=lambda sec:None,alive=lambda:True,limit=4);assert not launches

@pytest.mark.parametrize('worker_consumes_stop',[True,False])
def test_intentional_stop_never_respawns(tmp_path,worker_consumes_stop):
 count=[0];sleep_count=[0]
 class Child:
  pid=99
  def poll(self):return 0 if R.stop_marker(tmp_path).exists() else None
 def spawn():count[0]+=1;return Child()
 def sleep(sec):
  sleep_count[0]+=1
  if sleep_count[0]==2:
   if worker_consumes_stop:R.mark_stop(tmp_path)
   else:(tmp_path/'stop').touch()
 reason=S.run(tmp_path,spawn=spawn,sleep=sleep,alive=lambda:False,limit=20)
 assert reason=='intentional_stop' and count[0]==1 and R.stop_marker(tmp_path).exists()

def test_mutex_guard_with_fake_native_api(tmp_path,monkeypatch):
 import ctypes
 class Fn:
  def __init__(self,f):self.f=f
  def __call__(self,*a):return self.f(*a)
 class Kernel:
  def __init__(self):self.items={};self.handles={};self.next=1;self.err=0;self.CreateMutexW=Fn(self.create);self.OpenMutexW=Fn(self.open);self.CloseHandle=Fn(self.close)
  def handle(self,name):
   h=self.next;self.next+=1;self.handles[h]=name;self.items[name]=self.items.get(name,0)+1;return h
  def create(self,a,b,name):self.err=183 if name in self.items else 0;return self.handle(name)
  def open(self,access,inherit,name):return self.handle(name) if name in self.items else 0
  def close(self,h):
   name=self.handles.pop(h);self.items[name]-=1
   if not self.items[name]:del self.items[name]
 k=Kernel();monkeypatch.setattr(ctypes,'WinDLL',lambda *a,**kw:k,raising=False);monkeypatch.setattr(ctypes,'get_last_error',lambda:k.err,raising=False);monkeypatch.setattr(ctypes,'set_last_error',lambda value:setattr(k,'err',value),raising=False)
 first=R.Singleton(tmp_path,'listener');assert first.acquire();assert R.exists(tmp_path,'listener');second=R.Singleton(tmp_path,'listener');assert not second.acquire();first.close();assert not R.exists(tmp_path,'listener');assert second.acquire();second.close()

def test_launcher_shims_point_into_the_package():
 import jarvis_supervisor,jarvis_voice
 assert jarvis_supervisor.run is S.run and jarvis_supervisor.entry is S.entry and jarvis_voice.run.__module__=='jarvis.app.main'

def test_supervisor_imports_only_the_stdlib():
 import subprocess,sys
 code="import sys,jarvis_supervisor;print(sorted(m for m in ('numpy','scipy','sounddevice','onnxruntime','vosk','torch') if m in sys.modules))"
 out=subprocess.run([sys.executable,'-c',code],cwd=str(S.PATHS.SOURCE_DIR),capture_output=True,text=True,timeout=60)
 assert out.returncode==0 and out.stdout.strip()=='[]',out.stderr
