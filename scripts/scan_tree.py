"""Conservative source-only preflight. Findings print locations/categories, never values.
Not a substitute for gitleaks or a manual review of the full Git history.
"""
import argparse,ast,collections,fnmatch,json,math,re,subprocess
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit
SKIP_DIRS={'.git','__pycache__','.pytest_cache','.venv','venv'}
SECRET_PATTERNS={
 'private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
 'github_token':r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})\b',
 'aws_access_key':r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b',
 'google_api_key':r'\bAIza[0-9A-Za-z_-]{30,}\b',
 'jwt':r'\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b',
 'slack_token':r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b',
 'absolute_windows_user_path':r'(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s]+',
 'ipv4_literal':r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',
}
OFFICIAL_HOSTS={'github.com','download.pytorch.org','alphacephei.com','platform.fatsecret.com','www.google.com','www.youtube.com','example.invalid','img.shields.io','keepachangelog.com','semver.org'}
BAD_NAMES=['*.bak*','.env','.env.*','*.env','config.json','config.legacy.json','notes.md','*.log','*.wav','*.mp3','*.ogg','*.pt','*.pth','*.onnx','*.tflite','*.zip','*.pem','*.key']
def entropy(text: str) -> float:
 return -sum(n/len(text)*math.log2(n/len(text)) for n in collections.Counter(text).values())
def scan(root: Path, forbidden: Iterable[str] = (), staged: bool = False) -> tuple[int, list[dict[str, Any]]]:
 findings: list[dict[str, Any]] = [];files: list[Path] = []
 if staged:
  raw=subprocess.check_output(['git','-C',str(root),'ls-files','-z'])
  files=[root/p for p in raw.decode().split('\0') if p]
 else:files=[p for p in root.rglob('*') if p.is_file() and not any(s in SKIP_DIRS for s in p.relative_to(root).parts)]
 for p in files:
  name=str(p.relative_to(root)).replace('\\','/')
  def flag(kind: str, line: int = 0, name: str = name) -> None:findings.append({'file':name,'line':line,'category':kind})
  if any(fnmatch.fnmatch(p.name,pat) for pat in BAD_NAMES):flag('forbidden_filename')
  try:text=p.read_text(encoding='utf-8-sig')
  except UnicodeError:flag('unexpected_binary');continue
  for kind,pattern in SECRET_PATTERNS.items():
   for m in re.finditer(pattern,text):
    line=text.count('\n',0,m.start())+1
    if kind=='ipv4_literal' and p.name.startswith('requirements') and re.fullmatch(r'[A-Za-z0-9_.-]+==[0-9]+(?:\.[0-9]+){3}',text.splitlines()[line-1].strip()):continue
    flag(kind,line)
  for word in forbidden:
   for m in re.finditer(re.escape(word),text,re.I):flag('private_literal',text.count('\n',0,m.start())+1)
  for m in re.finditer(r'https?://[^\s<>"\x27)]+',text):
   value=m.group().rstrip('.,;`')
   try:url=urlsplit(value)
   except ValueError:continue
   if url.username or url.password or re.search(r'(?i)(?:token|secret|password|api_key)=',url.query):flag('credential_in_url',text.count('\n',0,m.start())+1)
   if url.hostname and re.fullmatch(r'[A-Za-z0-9.-]+',url.hostname) and url.hostname not in OFFICIAL_HOSTS:flag('unreviewed_url',text.count('\n',0,m.start())+1)
  if p.suffix=='.py':
   try:tree=ast.parse(text)
   except SyntaxError:flag('python_syntax');continue
   for n in ast.walk(tree):
    if not isinstance(n,ast.Constant) or not isinstance(n.value,str):continue
    v=n.value
    if len(v)>=28 and re.fullmatch(r'[A-Za-z0-9_+/=-]+',v) and not re.fullmatch(r'[A-Z_0-9]+',v) and not v.startswith(('dummy_','fixture_','Synthetic')) and entropy(v)>4.1:flag('review_high_entropy_literal',n.lineno)
  if p.suffix=='.json':
   try:obj=json.loads(text)
   except ValueError:flag('json_syntax');continue
   def check_fields(value: Any) -> None:
    if isinstance(value,dict):
     for k,v in value.items():
      if re.search(r'(?i)(?:webhook_auth|password|api_key|consumer_secret|access_token|access_secret)',k) and isinstance(v,str) and v and not v.startswith(('dummy_','fixture_','PASTE_')):flag('credential_literal')
      check_fields(v)
    elif isinstance(value,list):
     for v in value:check_fields(v)
   check_fields(obj)
 return len(files),findings

def main() -> None:
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path,nargs='?',default=Path(__file__).resolve().parent.parent);p.add_argument('--forbid',action='append',default=[]);p.add_argument('--staged',action='store_true');a=p.parse_args()
 count,findings=scan(a.root.resolve(),a.forbid,a.staged)
 print(json.dumps({'files_scanned':count,'findings':findings},ensure_ascii=True,indent=2))
 raise SystemExit(1 if findings else 0)
if __name__=='__main__':main()
