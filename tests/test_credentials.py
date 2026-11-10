import importlib.util,io,json,urllib.parse
from pathlib import Path
import pytest
from jarvis.adapters import credentials as C
ROOT=Path(__file__).resolve().parent.parent
class MemoryBackend:
 def __init__(self):self.values={}
 def set_password(self,s,u,p):self.values[s,u]=p
 def get_password(self,s,u):return self.values.get((s,u))
@pytest.fixture
def memory(monkeypatch):
 b=MemoryBackend();monkeypatch.setattr(C,'backend',lambda:b);return b
@pytest.mark.parametrize('name',C.NAMES)
def test_scoped_keyring_roundtrip(memory,name):
 C.set_secret(name,'dummy_'+name);assert C.get_secret(name)=='dummy_'+name
 assert list(memory.values)==[(C.service(name),'Jarvis')]
def test_name_scope(memory):
 with pytest.raises(ValueError):C.set_secret('OTHER_APP','dummy')
 assert not memory.values
@pytest.mark.parametrize('available',[True,False])
def test_webhook_keyring_and_file_fallback(tmp_path,memory,available):
 (tmp_path/'config.legacy.json').write_text(json.dumps({'webhook_auth_header':'dummy_backup'}),encoding='utf-8')
 if available:C.set_secret('webhook_auth_header','dummy_keyring')
 assert C.webhook({},tmp_path)==('dummy_keyring' if available else 'dummy_backup')
@pytest.mark.parametrize('source',['keyring','env','active_file','backup_file'])
def test_fatsecret_all_compatibility_sources(tmp_path,memory,source):
 path=tmp_path/'.env';values={n:'dummy_'+n for n in C.NAMES[1:]};env={}
 if source=='keyring':
  for n,v in values.items():C.set_secret(n,v)
 elif source=='env':env=values
 else:
  p=path if source=='active_file' else Path(str(path)+'.legacy');p.write_text('\n'.join(n+'='+v for n,v in values.items()),encoding='utf-8')
 result=C.fatsecret_env(env,path);assert all(result[n]==v for n,v in values.items())
def test_no_backend_errors_or_leaks(tmp_path,monkeypatch):
 class Broken:
  def get_password(self,*a):raise OSError('dummy backend unavailable')
 monkeypatch.setattr(C,'backend',lambda:Broken());assert C.get_secret('webhook_auth_header') is None;assert C.webhook({'webhook_auth_header':'dummy_legacy'},tmp_path)=='dummy_legacy'
def test_fatsecret_signer_mock_http(tmp_path,memory,monkeypatch):
 from jarvis.adapters import fatsecret as FS
 for n in C.NAMES[1:]:C.set_secret(n,'dummy_'+n)
 monkeypatch.setenv('FATSECRET_ENV_FILE',str(tmp_path/'fatsecret'/'.env'));sent=[]
 class Response(io.BytesIO):
  def __enter__(self):return self
  def __exit__(self,*a):self.close()
 def fake(req,**kw):sent.append(urllib.parse.parse_qs(req.data.decode()));return Response(b'{"ok":true}')
 monkeypatch.setattr(FS,'urlopen',fake);assert FS.call('food_entries.get',{'date':'1'})=={'ok':True};assert sent[0]['oauth_consumer_key']==['dummy_FATSECRET_CLIENT_ID'];assert sent[0]['oauth_signature']
 with pytest.raises(ValueError):FS.call('food_entries.get',{'oauth_token':'do_not_override'})
def test_fatsecret_cli_shim_prints_one_json_object(monkeypatch,capsys):
 spec=importlib.util.spec_from_file_location('fatsecret_cli_fixture',ROOT/'src'/'fatsecret_call.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 monkeypatch.setattr(m,'call',lambda method,params:{'method':method,**params})
 assert m.main(['food.get','{"food_id":"1"}'])==0 and json.loads(capsys.readouterr().out)=={'method':'food.get','food_id':'1'}
 assert m.main(['food.get','[1]'])==1 and json.loads(capsys.readouterr().out)=={'local_error':'params must be a JSON object'}
