"""Persistent local timers, reminders and announcements (survive a restart)."""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger("jarvis")


class PersistentTimers:
    """Timers, reminders and notices in cache/timers.json; a corrupt store is kept read-only."""

    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time) -> None:
        self.path=Path(path);self.clock=clock;self.lock=threading.RLock();self.items: list[dict[str, Any]] = [];self.error: str | None = None
        try:
            if self.path.exists():
                data=json.loads(self.path.read_text(encoding='utf-8-sig'))
                assert data.get('version')==1 and isinstance(data['items'],list)
                for r in data['items']:
                    assert isinstance(r,dict) and isinstance(r['due'],(int,float)) and isinstance(r['interval'],(int,float)) and math.isfinite(r['due']) and math.isfinite(r['interval']) and r['interval']>=0 and r['kind'] in ('timer','reminder','notice') and isinstance(r['label'],str)
                self.items=data['items']
        except Exception as e:self.error=type(e).__name__;log.warning('timer store invalid (%s); preserving file read-only',self.error)
    def _save(self) -> None:
        if self.error:raise ValueError('timer_store_invalid')
        self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_name(self.path.name+'.tmp')
        tmp.write_text(json.dumps({'version':1,'items':self.items},ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,self.path)
    def add(self, secs: float, label: str, interval: float = 0, kind: str = 'timer', group: str | None = None) -> str:
        if secs<=0 or interval<0:raise ValueError('invalid_duration')
        with self.lock:
            if self.error:raise ValueError('timer_store_invalid')
            r={'id':uuid.uuid4().hex,'due':self.clock()+secs,'interval':interval,'kind':kind,'label':label,'group':group};self.items.append(r)
            try:self._save()
            except Exception:self.items.remove(r);raise
            return str(r['id'])
    def cancel(self, kinds: Iterable[str] | None = None) -> int:
        with self.lock:
            keep=set(kinds or ());old=self.items;self.items=[r for r in old if keep and r['kind'] not in keep]
            try:self._save()
            except Exception:self.items=old;raise
            return len(old)-len(self.items)
    def cancel_groups(self, groups: Iterable[str]) -> int:
        with self.lock:
            drop=set(groups);old=self.items;self.items=[r for r in old if r.get("group") not in drop]
            try:self._save()
            except Exception:self.items=old;raise
            return len(old)-len(self.items)
    def pop_fired(self, limit: int = 1, kinds: Iterable[str] | None = None) -> list[dict[str, str]]:
        """Fired items, oldest first; with ``kinds`` only those (the rest wait for their turn)."""
        only=None if kinds is None else frozenset(kinds)
        with self.lock:
            if self.error:return []
            now=self.clock();out: list[dict[str, str]] = [];changed=False;old=[dict(r) for r in self.items]
            for r in sorted(list(self.items),key=lambda x:x['due']):
                if len(out)>=limit:break
                if r['due']>now or (only is not None and r['kind'] not in only):continue
                out.append({'label':r['label'],'kind':r['kind']});changed=True
                if r['interval']:r['due']+=((now-r['due'])//r['interval']+1)*r['interval']
                else:self.items.remove(r)
            if changed:
                try:self._save()
                except Exception:self.items=old;raise
            return out
