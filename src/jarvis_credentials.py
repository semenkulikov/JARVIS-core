"""Scoped Windows Credential Manager access, via python-keyring. Never logs values.
Only Jarvis-owned credential names are addressable; restricted legacy files are fallback.
"""
import json,os,sys
from pathlib import Path
import jarvis_paths as PATHS
NAMES=('webhook_auth_header','FATSECRET_CLIENT_ID','FATSECRET_OAUTH1_CONSUMER_SECRET','FATSECRET_ACCESS_TOKEN','FATSECRET_ACCESS_SECRET')
_BACKEND=None

def backend():
 global _BACKEND
 if _BACKEND is not None:return _BACKEND
 if os.name!='nt':return None
 try:
  from keyring.backends.Windows import WinVaultKeyring
 except ImportError:
  # FatSecret CLI may use system Python. Reuse this app's installed pure-Python keyring.
  site=Path(__file__).resolve().parent.parent/'.venv'/'Lib'/'site-packages'
  if not site.is_dir():return None
  site_s=str(site)
  sys.path.insert(0,site_s)
  try:
   from keyring.backends.Windows import WinVaultKeyring
   _BACKEND=WinVaultKeyring()
   return _BACKEND
  except ImportError:
   return None
  finally:
   try:sys.path.remove(site_s)
   except ValueError:pass
 _BACKEND=WinVaultKeyring();return _BACKEND

def service(name):
 if name not in NAMES:raise ValueError('unsupported_credential_name')
 return PATHS.credential_prefix()+name

def get_secret(name):
 try:
  b=backend();return b.get_password(service(name),'Jarvis') if b is not None else None
 except Exception:return None

def set_secret(name,value):
 b=backend()
 if b is None:raise RuntimeError('Windows_keyring_unavailable')
 b.set_password(service(name),'Jarvis',value)

def legacy_env(path):
 values={}
 try:
  for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
   if line.strip() and not line.lstrip().startswith('#') and '=' in line:
    k,v=line.split('=',1)
    if k.strip() in NAMES:values[k.strip()]=v.strip()
 except OSError:pass
 return values

def webhook(cfg,base):
 value=get_secret('webhook_auth_header')
 if value:return value
 value=cfg.get('webhook_auth_header','')
 if value and 'PASTE' not in value:return value
 try:
  old=json.loads((Path(base)/'config.legacy.json').read_text(encoding='utf-8-sig'));return old.get('webhook_auth_header',value)
 except (OSError,ValueError,TypeError):return value

def fatsecret_env(env,path):
 out=dict(env);old=None;backup=None
 for name in NAMES[1:]:
  value=get_secret(name) or env.get(name)
  if not value:
   if old is None:old=legacy_env(path)
   value=old.get(name)
  if not value:
   if backup is None:backup=legacy_env(str(path)+'.legacy')
   value=backup.get(name)
  if value:out[name]=value
 return out
