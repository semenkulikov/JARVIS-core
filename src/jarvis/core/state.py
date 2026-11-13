"""Listener state: the mode machine, the data of the current conversation and shared signals.

One conversation runs at a time (``Signals.busy``); the conversation thread owns
:class:`ListenerState` while it runs and the audio loop only reads it. A server request outlives
the conversation that asked it: it is a :class:`ServerJob` that the background worker fills with
reply parts, spoken later in a turn of its own.
"""
from __future__ import annotations

import enum
import logging
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

log = logging.getLogger("jarvis")


class Mode(enum.Enum):
    IDLE = "idle"              # waiting for the name or a clap
    LISTENING = "listening"    # recording a phrase
    PROCESSING = "processing"  # routing, running a command, waiting for the server
    SPEAKING = "speaking"      # playing synthesized speech
    FOLLOWUP = "followup"      # listening without the name after a reply
    SLEEP = "sleep"            # only «Джарвис, проснись» is accepted


TRANSITIONS: Mapping[Mode, frozenset[Mode]] = {
    Mode.IDLE: frozenset({Mode.LISTENING, Mode.PROCESSING, Mode.SLEEP}),
    Mode.SLEEP: frozenset({Mode.IDLE, Mode.PROCESSING}),
    Mode.LISTENING: frozenset({Mode.PROCESSING, Mode.IDLE}),
    Mode.PROCESSING: frozenset({Mode.SPEAKING, Mode.LISTENING, Mode.FOLLOWUP, Mode.IDLE}),
    Mode.SPEAKING: frozenset({Mode.PROCESSING, Mode.IDLE}),
    Mode.FOLLOWUP: frozenset({Mode.PROCESSING, Mode.IDLE}),
}


class ListenerFSM:
    """Current mode with checked transitions. A wrong transition is logged, never raised:
    the state machine documents and observes the flow, it must not break a conversation."""

    def __init__(self, mode: Mode = Mode.IDLE) -> None:
        self._mode = mode
        self._lock = threading.Lock()
        self.invalid = 0

    @property
    def mode(self) -> Mode:
        return self._mode

    def to(self, new: Mode, reason: str = "") -> bool:
        with self._lock:
            old = self._mode
            if new is old: return True
            ok = new is Mode.IDLE or new in TRANSITIONS[old]
            if not ok:
                self.invalid += 1
                log.warning("state %s -> %s is not a valid transition (%s)", old.value, new.value, reason)
            else:
                log.debug("state %s -> %s (%s)", old.value, new.value, reason)
            self._mode = new
            return ok

    def restore(self, prev: Mode, reason: str = "said") -> None:
        """Leave SPEAKING for the mode playback started from."""
        if self._mode is Mode.SPEAKING: self.to(prev if prev is not Mode.SPEAKING else Mode.PROCESSING, reason)

    @contextmanager
    def speaking(self, reason: str = "say") -> Iterator[None]:
        """SPEAKING for the duration of playback, then back to the mode it interrupted."""
        prev = self._mode
        self.to(Mode.SPEAKING, reason)
        try: yield
        finally: self.restore(prev)


@dataclass
class Signals:
    busy: threading.Event = field(default_factory=threading.Event)       # a conversation is running
    speaking: threading.Event = field(default_factory=threading.Event)   # audio is playing
    interrupt: threading.Event = field(default_factory=threading.Event)  # stop speech and the handler now


@dataclass
class ListenerState:
    """Data of the running conversation and of the last thing said."""
    capture: Any = None             # Capture that receives microphone frames, if recording
    model: Any = None               # loaded Vosk model
    speaking_text: str = ""         # what is being played, lower-case, for echo checks
    stop_pending: bool = False
    stop_ack_active: bool = False
    followup_guard: bool = False
    followup_eligible: bool = False
    last_spoken: str = ""
    last_spoken_end: float = 0.0
    speech_serial: int = 0
    trace: Any = None               # jarvis.core.perf.Trace of the current turn
    last_reply: str = ""            # last answer spoken, for «повтори» (a server job's whole answer so far)
    last_reply_private: bool = False
    reply_parts: list[str] = field(default_factory=list)
    last_input_conf: float = 1.0
    last_input_end: float | None = None
    last_capture: dict[str, Any] | None = None
    dropped: bool = False
    sleep_hint_at: float = 0.0
    drop_reason: str = ""           # why the router dropped the last phrase (gate.reject_reason and the like)
    reject_beep_at: float = 0.0     # monotonic time of the last «not understood» beep
    exit_code: int | None = None

    def perf(self, event: str, **meta: Any) -> None:
        if self.trace is not None: self.trace.mark(event, **meta)


@dataclass
class RequestLedger:
    """Server requests the user abandoned, and whether the server recently failed to answer."""
    cancelled: dict[str, float] = field(default_factory=dict)
    down_since: float | None = None

    def cancel(self, rid: str | None) -> None:
        if rid: self.cancelled[rid] = time.time()

    def is_cancelled(self, rid: str | None) -> bool:
        return rid in self.cancelled

    def recently_down(self, cfg: Mapping[str, Any], now: float | None = None) -> bool:
        t = self.down_since
        return t is not None and ((now or time.time()) - t) < float(cfg.get("server_down_ttl_s", 1800))


@dataclass(frozen=True)
class ReplyPart:
    """One piece of a server answer waiting to be spoken; dropped unspoken after ``expires`` (epoch)."""
    text: str
    expires: float
    data: bool = True               # False for the listener's own notices («сервер не отвечает»)


@dataclass(eq=False)
class ServerJob:
    """One request to the server: created by the conversation, filled by the worker, spoken by a reply turn.

    Thread-safe: the worker pushes parts while a reply turn pops them.
    """
    rid: str
    text: str
    kind: str
    created: float
    trigger: str = "wake_word"
    listener_ack: str = ""
    test: bool = False
    extra_payload: dict[str, Any] | None = None
    private: bool = False
    trace: Any = None               # jarvis.core.perf.Trace handed over by the asking turn
    spoken: list[str] = field(default_factory=list)
    finished: bool = False          # no more parts will come
    cancelled: bool = False
    _parts: deque[ReplyPart] = field(default_factory=deque, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    arrived: threading.Event = field(default_factory=threading.Event, repr=False)

    def push(self, text: str, expires: float, data: bool = True) -> None:
        with self._lock:
            if self.cancelled: return
            self._parts.append(ReplyPart(text, expires, data))
        self.arrived.set()

    def requeue(self, part: ReplyPart) -> None:
        """Put back a part whose playback was cut by a barge-in that did not cancel the job."""
        with self._lock:
            if not self.cancelled: self._parts.appendleft(part)

    def pop(self, now: float) -> ReplyPart | None:
        """Next part still worth speaking; expired parts are dropped with a log line."""
        with self._lock:
            while self._parts:
                part = self._parts.popleft()
                if now < part.expires: return part
                log.info("server reply part expired unspoken rid=%s (%d chars)", self.rid, len(part.text))
            self.arrived.clear()
            return None

    def has_parts(self, now: float) -> bool:
        with self._lock:
            return any(now < p.expires for p in self._parts)

    def finish(self) -> None:
        self.finished = True; self.arrived.set()

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True; self.finished = True; self._parts.clear()
        self.arrived.set()

    @property
    def done(self) -> bool:
        """Nothing left to wait for or to speak."""
        with self._lock:
            return self.cancelled or (self.finished and not self._parts)

    @property
    def last_reply(self) -> str:
        return " ".join(self.spoken)
