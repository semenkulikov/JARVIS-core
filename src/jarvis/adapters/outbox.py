"""The outbox: UTF-8 text files the server writes as replies (``<rid>.<n>.txt`` parts, ``<rid>.txt`` final)."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Mapping

from jarvis.core.state import RequestLedger

log = logging.getLogger("jarvis")


def read_text(p: str) -> str:
    """File text, retried while another process still holds it open; "" if it never frees up."""
    for _ in range(10):
        try:
            with open(p, encoding="utf-8-sig") as f: return f.read()
        except PermissionError: time.sleep(0.2)
    return ""



class OutboxSignal:
    """Wakes the outbox loop on a directory event (watchdog) or after a short poll interval."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.event = threading.Event()
        self.observer: Any = None
        self.mode = "polling"

    def start(self, enabled: bool = True, timeout: float = 0.02) -> str:
        if not enabled: return self.mode
        try:
            from watchdog.events import FileSystemEvent, FileSystemEventHandler
            from watchdog.observers import Observer
            signal = self

            class Handler(FileSystemEventHandler):
                def on_any_event(self, event: FileSystemEvent) -> None:
                    if not event.is_directory: signal.event.set()
            # watchdog 7 Windows batches until a quiet timeout; default 1s adds latency.
            observer = Observer(timeout=max(0.005, float(timeout)))
            observer.schedule(Handler(), self.path, recursive=False)
            observer.start()
            self.observer = observer; self.mode = "watchdog"
        except Exception as exc:
            log.warning("outbox watcher unavailable (%s); polling fallback", type(exc).__name__)
        log.info("outbox notification mode=%s", self.mode)
        return self.mode

    def clear(self) -> None: self.event.clear()

    def wait(self, cfg: Mapping[str, Any]) -> None:
        if self.observer is not None and not self.observer.is_alive():
            self.mode = "polling"
            log.warning("outbox watcher stopped; polling fallback")
            self.observer = None
        # Periodic scan also protects against dropped/coalesced Windows events.
        self.event.wait(float(cfg.get("outbox_watch_rescan_s", 1.0)) if self.mode == "watchdog" else float(cfg.get("outbox_poll_s", 0.12)))

    def stop(self) -> None:
        if self.observer is not None:
            self.observer.stop(); self.observer.join(timeout=2)
        self.event.set()


class Outbox:
    def __init__(self, path: str, done: str | None = None, signal: Any = None) -> None:
        self.path = path
        self.done = done or os.path.join(path, "done")
        self.signal = signal if signal is not None else OutboxSignal(path)

    def ensure(self) -> None:
        os.makedirs(self.done, exist_ok=True)

    def part(self, rid: str, n: int) -> str:
        return os.path.join(self.path, f"{rid}.{n}.txt")

    def final(self, rid: str) -> str:
        return os.path.join(self.path, f"{rid}.txt")

    def read(self, p: str) -> str:
        return read_text(p)

    def move_done(self, p: str) -> None:
        try: os.replace(p, os.path.join(self.done, os.path.basename(p)))
        except Exception as e: log.warning("move failed %s: %s", p, e)

    @staticmethod
    def ready(p: str, allow_empty: bool = False) -> bool:
        """Avoid playing partially-written files, without a fixed 200 ms penalty."""
        try:
            a = os.stat(p)
            time.sleep(0.08)
            b = os.stat(p)
            return (a.st_size > 0 or allow_empty) and (a.st_size, a.st_mtime_ns) == (b.st_size, b.st_mtime_ns)
        except OSError: return False

    @staticmethod
    def file_age(p: str) -> float:
        try: return max(0.0, time.time() - os.path.getmtime(p))
        except OSError: return 0.0

    @staticmethod
    def log_arrival(p: str, rid: str, label: str, txt: str, t0: float) -> None:
        try: lag = max(0.0, time.time() - os.path.getmtime(p))
        except OSError: lag = -1
        log.info("outbox %s (%d chars) rid=%s wait_s=%.3f file_age_s=%.3f", label, len(txt), rid, time.time() - t0, lag)

    def purge_cancelled(self, ledger: RequestLedger, max_age_s: float = 900) -> None:
        """Delete late files of abandoned requests; forget requests older than ``max_age_s``."""
        for rid_c, tc in list(ledger.cancelled.items()):
            if time.time() - tc > max_age_s: ledger.cancelled.pop(rid_c, None); continue
            for fn in os.listdir(self.path):
                if fn.startswith(rid_c):
                    try: os.remove(os.path.join(self.path, fn)); log.info("dropped cancelled outbox part %s", fn)
                    except Exception as e: log.info("drop failed %s: %s", fn, e)
