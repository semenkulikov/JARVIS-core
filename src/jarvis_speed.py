"""Lightweight stage-one latency, directory events and conservative intent routing."""
import datetime, difflib, json, logging, re, threading, time, uuid

log = logging.getLogger('jarvis')

class Trace:
    def __init__(self, trigger='wake_word', request_id=None):
        self.rid = request_id or str(uuid.uuid4())
        self.trigger = trigger
        self.t0 = time.perf_counter()
        self.wall = datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')
        self.events = {'wake': 0.0}
        self.meta = {}
        self.lock = threading.Lock()
        self.finished = False
        log.info('PERF event %s', json.dumps({'request_id':self.rid,'event':'wake','ms':0,'trigger':trigger},ensure_ascii=False))
    def mark(self, event, at=None, **meta):
        with self.lock:
            if self.finished or event in self.events: return
            ms = round(1000 * ((time.perf_counter() if at is None else at) - self.t0), 3)
            self.events[event] = ms
            self.meta.update(meta)
        log.info('PERF event %s', json.dumps({'request_id':self.rid,'event':event,'ms':ms,**meta},ensure_ascii=False))
    def finish(self, result='done'):
        self.mark('done')
        with self.lock:
            if self.finished: return
            self.finished = True
            row = {'request_id':self.rid,'started':self.wall,'trigger':self.trigger,'result':result,'events_ms':dict(self.events),**self.meta}
        log.info('PERF summary %s', json.dumps(row,ensure_ascii=False))

class OutboxSignal:
    def __init__(self, path):
        self.path = path
        self.event = threading.Event()
        self.observer = None
        self.mode = 'polling'
    def start(self, enabled=True, timeout=0.02):
        if not enabled: return self.mode
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
            signal = self
            class Handler(FileSystemEventHandler):
                def on_any_event(self, event):
                    if not event.is_directory: signal.event.set()
            # watchdog 7 Windows batches until a quiet timeout; default 1s adds latency.
            observer = Observer(timeout=max(0.005,float(timeout)))
            observer.schedule(Handler(),self.path,recursive=False)
            observer.start()
            self.observer = observer; self.mode = 'watchdog'
        except Exception as exc:
            log.warning('outbox watcher unavailable (%s); polling fallback',type(exc).__name__)
        log.info('outbox notification mode=%s',self.mode)
        return self.mode
    def clear(self): self.event.clear()
    def wait(self, cfg):
        if self.observer is not None and not self.observer.is_alive():
            self.mode = 'polling'
            log.warning('outbox watcher stopped; polling fallback')
            self.observer = None
        # Periodic scan also protects against dropped/coalesced Windows events.
        self.event.wait(float(cfg.get('outbox_watch_rescan_s',1.0)) if self.mode=='watchdog' else float(cfg.get('outbox_poll_s',0.12)))
    def stop(self):
        if self.observer is not None:
            self.observer.stop(); self.observer.join(timeout=2)
        self.event.set()

_MUTATION = re.compile(r'\b(?:добав\w*|созда\w*|удал\w*|постав\w*|отмен\w*|измени\w*|перенес\w*|отмет\w*|выполн\w*|закро\w*|заверш\w*|напомни\w*|открой|запиши|почему|объясни)\b')
_STOP = {'у','меня','мне','на','по','там','ну','а','что','какие','как','сэр','пожалуйста','сегодня'}

def norm(text):
    words = re.sub(r'[^\w\s]',' ',(text or '').lower().replace('ё','е')).split()
    words = ['что' if w in ('че','чо') else w for w in words]
    return ' '.join(w for w in words if w not in ('ну','сэр','пожалуйста'))

def fuzzy_alias(text,cfg):
    if not cfg.get('intent_fuzzy_enabled',True): return None
    text = norm(text)
    words = text.split()
    if not words or len(words)>int(cfg.get('intent_max_words',8)) or _MUTATION.search(text): return None
    anchors = [w for w in words if w not in _STOP]
    if not anchors: return None
    try:
        from rapidfuzz.fuzz import ratio, token_sort_ratio
        score = lambda a,b:max(ratio(a,b),token_sort_ratio(a,b))
        engine='rapidfuzz'
    except ImportError:
        score=lambda a,b:100*difflib.SequenceMatcher(None,a,b).ratio()
        engine='difflib-fallback'
    ranked={}
    for alias in cfg.get('aliases',[]):
        if alias.get('action') not in ('status','cache_field','time','workout'): continue
        intent=(alias.get('action'),alias.get('field'))
        for phrase in alias.get('phrases',[]):
            phrase=norm(phrase); pw=phrase.split()
            # Require a meaningful shared/similar content word; no token-set subset match.
            pa=[w for w in pw if w not in _STOP]
            if not pa or not any(score(a,b)>=82 for a in anchors for b in pa): continue
            value=score(text,phrase)
            if value>ranked.get(intent,(0,None))[0]: ranked[intent]=(value,alias)
    ranks=sorted(ranked.values(),key=lambda x:x[0],reverse=True)
    threshold=float(cfg.get('intent_fuzzy_threshold',88))
    margin=float(cfg.get('intent_fuzzy_margin',7))
    if not ranks or ranks[0][0]<threshold or (len(ranks)>1 and ranks[0][0]-ranks[1][0]<margin): return None
    value,alias=ranks[0]
    log.info('intent fuzzy engine=%s name=%s score=%.1f',engine,alias.get('name'),value)
    return dict(alias, _fuzzy=True, _fuzzy_score=round(value,1))

def template_phrases(cfg,jt,now=None):
    """Whole-sentence WAV templates, bounded preload; never splice number waveforms."""
    now=now or datetime.datetime.now()
    out=[]
    for i in range(max(0,min(5,int(cfg.get('time_preload_minutes',3))))):
        t=now+datetime.timedelta(minutes=i)
        out.append('Сейчас '+jt.time_words(t.hour,t.minute)+', сэр.')
    for n in (1,5,10,15,30,45):
        out.append('Таймер на '+jt.num_ru(n,'f')+' '+jt.plural(n,'минуту','минуты','минут')+', сэр.')
    out.append('Таймер на один час, сэр.')
    return out
