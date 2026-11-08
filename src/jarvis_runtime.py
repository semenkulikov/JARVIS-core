"""Small Windows singleton and intentional-stop primitives; no side effects on import."""
import ctypes,hashlib,os,time
from pathlib import Path

def stop_marker(base):return Path(base)/'cache'/'intentional_stop'
def mark_stop(base):
 p=stop_marker(base);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(str(time.time()),encoding='ascii')
def clear_stop(base):
 for p in (stop_marker(base),Path(base)/'stop'):
  try:p.unlink()
  except FileNotFoundError:pass

def mutex_name(base,role):return 'Local\\JarvisVoiceAssistant_'+hashlib.sha256(str(Path(base).resolve()).lower().encode()).hexdigest()[:16]+'_'+role
class Singleton:
 def __init__(self,base,role):self.name=mutex_name(base,role);self.handle=None;self.api=None
 def acquire(self):
  k=ctypes.WinDLL('kernel32',use_last_error=True);k.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p];k.CreateMutexW.restype=ctypes.c_void_p;k.CloseHandle.argtypes=[ctypes.c_void_p]
  ctypes.set_last_error(0);h=k.CreateMutexW(None,0,self.name);error=ctypes.get_last_error()
  if not h:raise OSError('singleton_mutex_failed')
  if error==183:k.CloseHandle(h);return False
  self.handle=h;self.api=k;return True
 def close(self):
  if self.handle:self.api.CloseHandle(self.handle);self.handle=None

def exists(base,role):
 k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenMutexW.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_wchar_p];k.OpenMutexW.restype=ctypes.c_void_p;k.CloseHandle.argtypes=[ctypes.c_void_p]
 h=k.OpenMutexW(0x100000,0,mutex_name(base,role))
 if h:k.CloseHandle(h);return True
 return False

def crash_delay(failures,minimum=2,maximum=300):return min(maximum,minimum*2**max(0,min(16,failures-1)))
