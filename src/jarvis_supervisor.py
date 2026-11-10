"""User-level, hidden, stdlib-only listener supervisor. Started by existing VBS/logon.
Intentional stop exits supervisor too; only an explicit VBS start resumes it.
"""
import logging,os,subprocess,sys,time
from logging.handlers import RotatingFileHandler
from pathlib import Path
import jarvis_runtime as R
import jarvis_paths as PATHS
from jarvis_paths import HOME, SOURCE_DIR
BASE=HOME
log=logging.getLogger('jarvis.supervisor')

def spawn_worker():
 exe=Path(sys.executable)
 if os.name=='nt' and exe.with_name('pythonw.exe').is_file():exe=exe.with_name('pythonw.exe')
 return subprocess.Popen([str(exe),str(SOURCE_DIR/'jarvis_voice.py')],cwd=str(HOME),creationflags=0x08000000 if os.name=='nt' else 0)

def run(base=BASE,spawn=None,sleep=time.sleep,clock=time.monotonic,alive=None,limit=None):
 base=Path(base);spawn=spawn or spawn_worker
 alive=alive or (lambda:R.exists(base,'listener'));child=None;failures=0;started=clock();retry_at=0;steps=0
 while limit is None or steps<limit:
  steps+=1
  if (base/'stop').exists():R.mark_stop(base)
  intentional=R.stop_marker(base).exists()
  if child is not None:
   code=child.poll()
   if code is not None:
    log.info('worker exited code=%s intentional=%s',code,intentional);child=None
    if intentional:return 'intentional_stop'
    failures=1 if clock()-started>=300 else failures+1;retry_at=clock()+R.crash_delay(failures);log.warning('crash recovery delay_s=%d failures=%d',R.crash_delay(failures),failures)
  if intentional:
   if child is None and not alive():
    # The listener may already have consumed stop. Retain marker, never auto-resume.
    try:(base/'stop').unlink()
    except FileNotFoundError:pass
    return 'intentional_stop'
  elif child is None and clock()>=retry_at and not alive():
   try:child=spawn();started=clock();log.info('listener launched pid=%s',getattr(child,'pid','fixture'))
   except Exception as e:
    failures+=1;retry_at=clock()+R.crash_delay(failures);log.warning('launch failed type=%s delay_s=%d',type(e).__name__,R.crash_delay(failures))
  sleep(.5)
 return 'test_limit'

def main():
 folder=PATHS.log_dir();folder.mkdir(parents=True,exist_ok=True);handler=RotatingFileHandler(folder/'supervisor.log',maxBytes=500000,backupCount=2,encoding='utf-8');handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));log.addHandler(handler);log.setLevel(logging.INFO)
 guard=R.Singleton(BASE,'supervisor')
 acquired=guard.acquire()
 # An explicit start just after listener exit may overlap the old supervisor's final poll.
 if not acquired and R.stop_marker(BASE).exists():
  deadline=time.monotonic()+5
  while time.monotonic()<deadline and not acquired:time.sleep(.25);acquired=guard.acquire()
 if not acquired:log.info('supervisor already running; duplicate start ignored');return
 try:
  R.clear_stop(BASE);log.info('supervisor start pid=%s',os.getpid());reason=run();log.info('supervisor exit reason=%s',reason)
 finally:guard.close()
if __name__=='__main__':
 try:main()
 except Exception as e:log.error('supervisor fatal type=%s',type(e).__name__)
