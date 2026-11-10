"""Latency trace of one request: ``PERF event`` lines while it runs, one ``PERF summary`` at the end.

scripts/latency_summary.py reads these lines; their JSON shape is a contract.
"""
from __future__ import annotations

import datetime
import json
import logging
import threading
import time
import uuid
from typing import Any

log = logging.getLogger("jarvis")


class Trace:
    def __init__(self, trigger: str = "wake_word", request_id: str | None = None) -> None:
        self.rid = request_id or str(uuid.uuid4())
        self.trigger = trigger
        self.t0 = time.perf_counter()
        self.wall = datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.events: dict[str, float] = {"wake": 0.0}
        self.meta: dict[str, Any] = {}
        self.lock = threading.Lock()
        self.finished = False
        log.info("PERF event %s", json.dumps({"request_id": self.rid, "event": "wake", "ms": 0, "trigger": trigger}, ensure_ascii=False))

    def mark(self, event: str, at: float | None = None, **meta: Any) -> None:
        with self.lock:
            if self.finished or event in self.events: return
            ms = round(1000 * ((time.perf_counter() if at is None else at) - self.t0), 3)
            self.events[event] = ms
            self.meta.update(meta)
        log.info("PERF event %s", json.dumps({"request_id": self.rid, "event": event, "ms": ms, **meta}, ensure_ascii=False))

    def finish(self, result: str = "done") -> None:
        self.mark("done")
        with self.lock:
            if self.finished: return
            self.finished = True
            row = {"request_id": self.rid, "started": self.wall, "trigger": self.trigger, "result": result,
                   "events_ms": dict(self.events), **self.meta}
        log.info("PERF summary %s", json.dumps(row, ensure_ascii=False))
