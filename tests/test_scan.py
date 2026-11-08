"""Scanner fixtures manufacture synthetic patterns, never use real credentials."""
import importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('scanner',ROOT/'scripts'/'scan_tree.py')
S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)

@pytest.mark.parametrize('filename,text,category',[
 ('sample.txt','ghp_'+'z'*36,'github_token'),
 ('sample.txt','.'.join(map(str,[192,0,2,1])),'ipv4_literal'),
 ('config.json','{}','forbidden_filename'),
 ('sample.json',json.dumps({'webhook_auth_header':'not-a-real-secret'}),'credential_literal'),
 ('sample.txt','https://'+'unknown.invalid/path','unreviewed_url')])
def test_scanner_reports_location_not_value(tmp_path,filename,text,category):
 (tmp_path/filename).write_text(text,encoding='utf-8')
 _,findings=S.scan(tmp_path)
 assert any(x['category']==category for x in findings)
 assert text not in json.dumps(findings)

def test_four_part_package_version_not_ip(tmp_path):
 (tmp_path/'requirements.txt').write_text('ruaccent=='+'.'.join(map(str,[1,5,8,3]))+'\n',encoding='utf-8')
 assert S.scan(tmp_path)[1]==[]
