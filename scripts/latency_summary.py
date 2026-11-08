"""Read PERF summary lines; never loads config or credentials. Python stdlib only."""
import argparse, json, statistics, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"src"))
from jarvis_paths import HOME

PAIRS=[('wake->recognized','wake','recognized'),('speech_end->recognized','speech_end','recognized'),('recognized->route','recognized','route'),('route->ack','route','ack_start'),('ack->file','ack_start','first_server_file'),('file->reply_audio','first_server_file','first_reply_audio'),('wake->audio','wake','first_audio'),('wake->done','wake','done')]
def load(path):
    for line in Path(path).read_text(encoding='utf-8-sig',errors='replace').splitlines():
        if 'PERF summary ' not in line: continue
        try: yield json.loads(line.split('PERF summary ',1)[1])
        except (ValueError,IndexError): continue

def main():
    p=argparse.ArgumentParser();p.add_argument('log',nargs='?',default=str(HOME/'logs'/'jarvis_voice.log'));p.add_argument('--last',type=int,default=20);p.add_argument('--include-tests',action='store_true');a=p.parse_args()
    rows=[r for r in load(a.log) if r.get('result') not in ('silence','echo','fragment') and (a.include_tests or not r.get('test'))][-max(1,a.last):]
    print('request_id | started (explicit zone) | route | result | first audio ms | done ms')
    for r in rows:
        e=r['events_ms'];print(r['request_id'],'|',r.get('started'),'|',r.get('route','?'),'|',r.get('result'),'|',e.get('first_audio','-'),'|',e.get('done','-'))
    print('\ninterval | n | median ms | p95 ms')
    for name,start,end in PAIRS:
        v=sorted(r['events_ms'][end]-r['events_ms'][start] for r in rows if start in r['events_ms'] and end in r['events_ms'])
        if v: print(name,'|',len(v),'|',round(statistics.median(v),2),'|',round(v[min(len(v)-1,int((len(v)-1)*0.95+0.999))],2))
if __name__=='__main__':main()
