"""Server requests outside the conversation: one background worker, a short queue of :class:`ServerJob`.

The conversation only submits a job and speaks its acknowledgement; the worker posts it, watches
the outbox and fills the job with reply parts. The listener starts a ``server_reply`` turn when the
oldest job has something to say and nobody else is talking, so local commands keep working while
the server thinks and never cancel the request. Only «стоп» during a reply cancels its job.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any, Callable

from jarvis.adapters.outbox import Outbox
from jarvis.core import gate as GATE
from jarvis.core.matching import pure_wait_filler
from jarvis.core.ports import Config, ServerTransport
from jarvis.core.state import RequestLedger, ServerJob

log = logging.getLogger("jarvis")
SERVER_DOWN_PHRASE = "Сервер не отвечает, сэр. Локальные команды работают."
SERVER_SLOW_PHRASE = "Сервер пока молчит, сэр. Подожду ещё немного."
NO_REPLY_PHRASE = "Ответ не пришёл, сэр. Попробуйте ещё раз позже."
SEND_FAILED_PHRASE = "Не получилось отправить запрос, сэр."
STILL_WORKING_PHRASE = "Ответ ещё готовится, сэр."
BUSY_PHRASE = "Я ещё занят предыдущим, сэр."
DEFAULTS: dict[str, Any] = {
    "server_queue_max": 2,             # jobs in flight (running + waiting); one more is refused
    "server_reply_expire_s": 600.0,    # a reply part nobody could hear for this long is dropped
    "server_reply_gap_s": 1.5,         # a reply turn waits this long for the next part before letting go
}


class ServerWorker:
    """Posts jobs one at a time and collects their outbox files; replies of different jobs never mix."""

    def __init__(self, transport: ServerTransport, outbox: Outbox, ledger: RequestLedger, config: Callable[[], Config],
                 clock: Callable[[], float] = time.time) -> None:
        self.transport, self.outbox, self.ledger, self.config, self.clock = transport, outbox, ledger, config, clock
        self._jobs: list[ServerJob] = []           # submission order, until spoken out or cancelled
        self._queue: queue.Queue[ServerJob] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.speaking: ServerJob | None = None     # job whose reply is being spoken right now
        self.paused: ServerJob | None = None       # job whose reply a barge-in cut; «стоп» right after cancels it

    # ------------------------------------------------------------ conversation side
    def submit(self, job: ServerJob, cfg: Config) -> bool:
        """Queue ``job``; False (nothing queued) when the queue is full."""
        limit = max(1, int(cfg.get("server_queue_max", DEFAULTS["server_queue_max"])))
        with self._lock:
            self._jobs = [j for j in self._jobs if not j.done]
            if len(self._jobs) >= limit:
                log.info("server queue full (%d) -> refused rid=%s", len(self._jobs), job.rid); return False
            self._jobs.append(job)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="server-worker", daemon=True); self._thread.start()
        self._queue.put(job)
        return True

    def pending(self) -> list[ServerJob]:
        with self._lock:
            return [j for j in self._jobs if not j.done]

    def ready(self) -> ServerJob | None:
        """The oldest unfinished job, if it has a part to speak now (a younger job waits its turn)."""
        now = self.clock()
        with self._lock:
            self._jobs = [j for j in self._jobs if not j.done]
            head = self._jobs[0] if self._jobs else None
        return head if head is not None and head.has_parts(now) else None

    def cancel(self, job: ServerJob | None, reason: str) -> None:
        """Abandon ``job``: no more parts, late files are deleted, the server's later writes too."""
        if job is None or job.cancelled: return
        job.cancel(); self.ledger.cancel(job.rid); self.outbox.drop(job.rid)
        if job.trace is not None: job.trace.finish("cancelled")
        log.info("server job cancelled rid=%s (%s)", job.rid, reason)

    def cancel_speaking(self, reason: str) -> bool:
        job = self.speaking
        self.cancel(job, reason)
        return job is not None

    def cancel_paused(self, reason: str) -> bool:
        """«Джарвис, стоп» first pauses the reply (priority wake), then this cancels it."""
        job, self.paused = self.paused, None
        self.cancel(job, reason)
        return job is not None

    # ------------------------------------------------------------ worker side
    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try: self.process(job)
            except Exception: log.exception("server job failed rid=%s", job.rid)
            finally: job.finish()

    def process(self, job: ServerJob) -> None:
        if job.cancelled: return
        cfg = self.config()
        ok = self.transport.call(job.rid, job.text, job.trigger, cfg, job.test, listener_ack=job.listener_ack, kind=job.kind,
                                 trace=job.trace, extra_payload=job.extra_payload)
        if job.cancelled: return
        if ok: self.wait(job, cfg)
        else: self._notice(job, SEND_FAILED_PHRASE, cfg)

    def _expires(self, cfg: Config) -> float:
        return self.clock() + float(cfg.get("server_reply_expire_s", DEFAULTS["server_reply_expire_s"]))

    def _notice(self, job: ServerJob, text: str, cfg: Config) -> None:
        job.push(text, self._expires(cfg), data=False)

    def wait(self, job: ServerJob, cfg: Config) -> bool:
        """Collect the outbox files of ``job`` until its final file; True when the server answered.

        Keeps the old timing rules: «сервер не отвечает» after ``server_down_wait_s`` when the server
        failed recently, a notice after ``server_notice_s``, the timeout ``reply_timeout_s``."""
        ledger, outbox, rid = self.ledger, self.outbox, job.rid
        t0 = time.time(); n = 1; fillers = 0
        real_data_seen = False; server_seen = False; slow_noticed = False
        was_down = ledger.recently_down(cfg, t0)
        trace = job.trace

        def take(txt: str) -> None:
            nonlocal real_data_seen
            if GATE.is_silent_reply(txt):
                if txt.strip(): log.info("server asked for silence rid=%s", rid)
                return
            if job.listener_ack and not real_data_seen and pure_wait_filler(txt):
                log.info("skipped redundant server filler rid=%s: %r", rid, txt); return
            real_data_seen = True
            job.push(txt, self._expires(cfg))

        def arrived() -> None:
            if trace is not None: trace.mark("first_server_file")

        final = outbox.final(rid)
        while time.time() - t0 < cfg["reply_timeout_s"]:
            if job.cancelled: log.info("reply wait for %s abandoned (cancelled)", rid); return False
            outbox.signal.clear()
            if not server_seen and (os.path.exists(final) or os.path.exists(outbox.part(rid, n))):
                server_seen = True; ledger.down_since = None
            el = time.time() - t0
            if not server_seen and was_down and el > float(cfg.get("server_down_wait_s", 45)):
                # Server already failed recently: do not hang for the full timeout again.
                ledger.cancel(rid); ledger.down_since = time.time()
                log.warning("server still silent rid=%s after %.0fs (down since earlier) -> local fallback", rid, el)
                self._notice(job, SERVER_DOWN_PHRASE, cfg); return False
            if not server_seen and not was_down and not slow_noticed and el > float(cfg.get("server_notice_s", 90)):
                slow_noticed = True; log.info("server silent rid=%s after %.0fs -> notice", rid, el)
                self._notice(job, SERVER_SLOW_PHRASE, cfg)
            # An initial acknowledgement is enough. No second "checking" announcement.
            if not job.listener_ack and not real_data_seen and fillers == 0 and el > max(12.0, float(cfg.get("wait_filler_s", 12))) \
                    and not os.path.exists(final) and not os.path.exists(outbox.part(rid, n)):
                fillers += 1; self._notice(job, STILL_WORKING_PHRASE, cfg)
            part = outbox.part(rid, n)
            if os.path.exists(part) and outbox.ready(part):
                arrived(); txt = outbox.read(part); outbox.log_arrival(part, rid, "part " + str(n), txt, t0)
                outbox.move_done(part); take(txt); n += 1; continue
            if os.path.exists(final) and outbox.ready(final, allow_empty=real_data_seen or outbox.file_age(final) >= 0.6):
                arrived()
                while os.path.exists(outbox.part(rid, n)):
                    p = outbox.part(rid, n); t = outbox.read(p); outbox.move_done(p); log.info("outbox part %d (%d chars)", n, len(t)); take(t); n += 1
                txt = outbox.read(final); outbox.log_arrival(final, rid, "final", txt, t0); outbox.move_done(final)
                take(txt); return True
            outbox.signal.wait(cfg)
        log.warning("reply timeout for %s", rid)
        if not server_seen and not real_data_seen:
            ledger.down_since = time.time(); ledger.cancel(rid)
            log.warning("server marked unresponsive (no outbox file for rid=%s)", rid)
            self._notice(job, SERVER_DOWN_PHRASE, cfg); return False
        self._notice(job, NO_REPLY_PHRASE, cfg)
        return False
