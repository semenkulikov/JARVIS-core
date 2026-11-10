"""Manage this application's own Windows Credential Manager entries; never echo values."""
import argparse,getpass,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src'))
from jarvis.adapters import credentials as C

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('action',choices=['set','check'])
 p.add_argument('name',choices=C.NAMES)
 a=p.parse_args()
 if a.action=='set':
  value=getpass.getpass('Value (hidden): ')
  if not value:raise SystemExit('Empty value refused')
  C.set_secret(a.name,value)
  if C.get_secret(a.name)!=value:raise SystemExit('Credential verification failed')
  print('Saved and verified; value not displayed.')
 else:print('Present' if C.get_secret(a.name) else 'Not available')
if __name__=='__main__':main()
