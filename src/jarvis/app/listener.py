"""The microphone loop: wake word, clap, barge-in while speaking, sleep mode and scheduled notices.

Runs on the main thread; every conversation runs on its own thread (Conversation.handle) while the
loop keeps feeding audio to the capture queue and the barge-in recognisers.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from jarvis.core import gate as GATE
from jarvis.core import proactive as PROACTIVE
from jarvis.adapters import runtime as RUNTIME
from jarvis.core import sleep as SLEEP
import laptop as LP
from jarvis.adapters.audio import AGC, CHUNK, SR, Capture, ClapDetector, frames_after, pick_device
from jarvis.adapters.outbox import read_text
from jarvis.adapters.process import mem_info, trim_memory
from jarvis.app.components import Components
from jarvis.app.conversation import Conversation
from jarvis.app.warmup import Warmup
from jarvis.core.matching import corroborated_stop, stop_candidate
from jarvis.core.perf import Trace
from jarvis.core.ports import Config
from jarvis.core.state import Mode
from jarvis.core.wake import PRIORITY_WAKE_WORDS, VOSK_WAKE_SKIP_S, VOSK_WAKE_TAIL_S

log = logging.getLogger("jarvis")
RING_S = 8
OWW_MODEL = "hey_jarvis_v0.1.onnx"
NEXT, STOP = "next", "stop"   # loop control from a phase: skip to the next frame / leave the loop


@dataclass
class Loop:
    """Mutable state of the microphone loop (one instance per run)."""

    cfg: Config
    pm: Any
    oww: Any
    clap: ClapDetector
    ring: collections.deque[tuple[int, np.ndarray]] = field(default_factory=lambda: collections.deque(maxlen=int(RING_S * SR / CHUNK)))
    pos: int = 0
    wrec: Any = None
    wbase: int = 0
    srec: Any = None
    sbase: int = 0
    wake_check: dict[str, Any] | None = None
    last_end: float = 0.0
    lastlvl: float = field(default_factory=time.time)
    lastmem: float = field(default_factory=time.monotonic)
    next_proactive: float = 0.0
    was_busy: bool = False
    sleeping: bool = False
    barge_armed: bool = False
    pending: int | None = None
    brec: Any = None
    brfree: Any = None
    free_last: tuple[float, str] = (0, "")
    bagc: Any = None
    last_clean: float = 0
    bframes: int = 0


class Listener:
    def __init__(self, c: Components, conversation: Conversation, warmup: Warmup, sd: Any) -> None:
        self.c, self.conversation, self.warmup, self.sd = c, conversation, warmup, sd

    # ------------------------------------------------------------ helpers
    def start(self, trig: str, pre: list[np.ndarray] | None = None, text: Any = None, test: bool = False, skip_s: float = 0.0) -> None:
        sig = self.c.signals
        sig.interrupt.clear(); sig.busy.set()
        cap = Capture(pre) if (text is None and pre is not None) else None
        self.c.state.capture = cap
        threading.Thread(target=self.conversation.handle, args=(trig, cap, text, test, skip_s, Trace(trig)), daemon=True).start()

    def do_stop(self, reason: str) -> None:
        log.info("STOP barge-in (%s): speech stopped", reason)
        self.c.signals.interrupt.set()  # the speech thread stops its own stream
        self.c.ledger.cancel(self.c.state.rid)
        self.c.state.stop_pending = True

    def _stop_requested(self) -> bool:
        return os.path.exists(self.c.paths.stop_file)

    def _consume_stop(self) -> None:
        RUNTIME.mark_stop(self.c.paths.home); os.remove(self.c.paths.stop_file)

    def _load_model(self, cfg: Config) -> bool:
        """Load Vosk in the background while the phrase cache warms; False when stopped meanwhile."""
        c = self.c
        c.asr.quiet()
        mdir = [d for d in os.listdir(c.paths.models) if d.startswith("vosk-model")]
        ready = threading.Event(); model_error: list[Exception] = []; model_box: list[Any] = []

        def warm_vosk() -> None:
            t0 = time.monotonic()
            try: model_box.append(c.asr.load_model(os.path.join(c.paths.models, mdir[0])))
            except Exception as e: model_error.append(e)
            finally:
                ready.set(); log.info("vosk background warmup %.3fs", time.monotonic() - t0)
        threading.Thread(target=warm_vosk, name="vosk-warmup", daemon=True).start()
        threading.Thread(target=self.warmup.run, args=(cfg,), name="tts-warmup", daemon=True).start()
        c.outbox.signal.start(cfg.get("outbox_watch_enabled", True), cfg.get("outbox_event_batch_s", 0.02))
        while not ready.wait(0.1):
            if self._stop_requested():
                self._consume_stop(); c.outbox.signal.stop(); return False
        if model_error: raise model_error[0]
        c.state.model = model_box[0]
        return True

    def _load_oww(self, cfg: Config) -> Any:
        if not cfg["oww_enabled"]: return None
        try:
            from openwakeword.model import Model as OWW
            oww = OWW(wakeword_models=[os.path.join(self.c.paths.models, OWW_MODEL)], inference_framework="onnx")
            log.info("openWakeWord loaded")
            return oww
        except Exception as e:
            log.warning("openWakeWord unavailable: %s", e)
            return None

    # ------------------------------------------------------------ run
    def run(self) -> None:
        c, sd = self.c, self.sd
        cfg = c.config.load()
        LP.TIMERS = c.controller.get().timers
        pm = c.proactive.get()
        if not self._load_model(cfg): return
        if c.sleep.get().active(): log.info("sleep mode active for %.0fs more", c.sleep.get().remaining())
        lp = Loop(cfg=cfg, pm=pm, oww=self._load_oww(cfg), clap=ClapDetector())
        dev = pick_device(sd, cfg)
        stream = c.mic.open(sd, dev)
        stream.start()
        from jarvis import __version__
        log.info("listening (v%s) on device %s: %s", __version__, dev,
                 sd.query_devices(dev)["name"] if dev is not None else sd.query_devices(kind="input")["name"])
        c.speaker.preload(cfg)
        lp.wrec = c.asr.wake_recognizer(); lp.lastlvl = time.time(); lp.lastmem = time.monotonic()
        while True:
            try:
                if self.step(lp) == STOP: break
            except Exception as e:
                log.exception("main loop error: %s", e); time.sleep(0.5)
        c.outbox.signal.stop()

    def step(self, lp: Loop) -> str | None:
        """One pass: housekeeping, then at most one microphone frame."""
        ctl = self._housekeeping(lp)
        if ctl is not None: return ctl
        try: x = self.c.mic.queue.get(timeout=0.3)
        except queue.Empty: return NEXT
        self._frame(lp, x)
        return None

    def _housekeeping(self, lp: Loop) -> str | None:
        c, busy, st = self.c, self.c.signals.busy, self.c.state
        if self._stop_requested():
            self._consume_stop(); log.info("stop file -> intentional exit"); c.signals.interrupt.set(); c.player.idle(1.0); return STOP
        if not busy.is_set() and os.path.exists(c.paths.test_trigger):
            tt = read_text(c.paths.test_trigger).strip(); os.remove(c.paths.test_trigger); lp.cfg = c.config.load()
            log.info("test_trigger %r", tt)
            if tt.lower() in ("clap",): self.start("clap", text="", test=True)
            elif tt.lower() in ("", "wake", "джарвис", "хей джарвис"): self.start("wake_word", text="", test=True)
            else: self.start("wake_word", text=tt, test=True)
        sleep = c.sleep.get()
        lp.sleeping = sleeping = sleep.active()
        idle = not busy.is_set() and not lp.was_busy
        if idle: c.fsm.to(Mode.SLEEP if sleeping else Mode.IDLE, "sleep" if sleeping else "awake")
        if idle and sleep.poll(c.paths.at(SLEEP.WAKE_FILE)):
            lp.srec = None; self.start("sleep_end", text=""); return NEXT
        cfg = lp.cfg
        if time.monotonic() >= lp.next_proactive:
            lp.next_proactive = time.monotonic() + max(1, float(cfg.get("proactive_tick_s", 5)))
            job = lp.pm.tick(cfg)
            if job: threading.Thread(target=self.conversation.request_morning, args=(job, dict(cfg)), name="morning-post", daemon=True).start()
            if not sleeping and not busy.is_set() and not lp.was_busy and lp.pending is None and not st.stop_pending:
                item = lp.pm.take(cfg)
                if item: self.start("proactive", text=item)
        if not sleeping and not busy.is_set() and not lp.was_busy and lp.pending is None and not st.stop_pending and lp.pm.can_speak(cfg):
            timers: Any = LP.TIMERS  # jarvis_commands timers since run()
            for notice in timers.pop_fired(limit=1): self.start("timer_fire", text=notice, test=False); break
        if time.time() - lp.lastlvl > cfg["level_log_interval_s"]:
            c.mic.levels.report(); lp.lastlvl = time.time()
        if time.monotonic() - lp.lastmem > float(cfg.get("memory_log_interval_s", 1800)):
            lp.lastmem = time.monotonic()
            if not busy.is_set() and RUNTIME.idle_for(st.last_spoken_end or 0.0, lp.lastmem) > float(cfg.get("memory_trim_idle_s", 900)):
                trim_memory()  # pages come back on demand; frees RAM for calls between uses
            m = mem_info()
            log.info("memory: ws=%dMB priv=%dMB peak_ws=%dMB threads=%d", m["ws"], m["priv"], m["peak_ws"], threading.active_count())
            if not busy.is_set() and RUNTIME.memory_over_limit(m["priv"], cfg.get("memory_restart_mb", 0)):
                log.warning("memory guard: priv=%dMB > %sMB while idle -> restart via supervisor", m["priv"], cfg.get("memory_restart_mb"))
                st.exit_code = RUNTIME.MEMORY_RESTART_CODE; return STOP
        return None

    def _frame(self, lp: Loop, x: np.ndarray) -> None:
        c = self.c
        st = lp.pos; lp.pos += len(x); lp.ring.append((st, x))
        c.mic.levels.add(x)
        i16 = (np.clip(x, -1, 1) * 32767).astype(np.int16)
        cap = c.state.capture
        if cap is not None: cap.q.put(x)
        sc = max(lp.oww.predict(i16).values()) if lp.oww is not None else 0.0
        if time.time() - lp.last_clean > 2:
            lp.last_clean = time.time()
            c.outbox.purge_cancelled(c.ledger)
        if c.signals.busy.is_set():
            self._while_busy(lp, x, st, sc, cap); return
        if lp.was_busy and self._after_busy(lp): return
        if lp.sleeping:
            self._while_sleeping(lp, st, i16); return
        lp.srec = None
        self._detect_wake(lp, x, st, i16, sc)

    def _while_busy(self, lp: Loop, x: np.ndarray, st: int, sc: float, cap: Capture | None) -> None:
        """Speaking or waiting for the server: listen for «стоп», a priority «Джарвис» or an openWakeWord barge-in."""
        c, cfg, state, interrupt = self.c, lp.cfg, self.c.state, self.c.signals.interrupt
        if not lp.was_busy:
            lp.brec = c.asr.stop_recognizer(cfg); lp.bagc = AGC(cfg)
            lp.brfree = c.asr.recognizer(); lp.free_last = (0, ""); lp.bframes = 0
        lp.was_busy = True
        if cap is None and not interrupt.is_set() and not state.stop_ack_active and not state.followup_guard:
            if os.path.exists(c.paths.test_bargein):
                tb = read_text(c.paths.test_bargein).strip(); os.remove(c.paths.test_bargein)
                log.info("test_bargein %r (speaking=%s)", tb, c.signals.speaking.is_set())
                self.do_stop("test: " + tb); return
            try:
                bb = (lp.bagc(x) * 32767).astype(np.int16).tobytes()
                borigin = st - lp.bframes; lp.bframes += len(x)
                if lp.brfree.AcceptWaveform(bb):
                    fr = json.loads(lp.brfree.Result())
                    fw = fr.get("result", [])
                    fc = sum(w.get("conf", 0) for w in fw) / max(1, len(fw))
                    lp.free_last = (time.monotonic(), fr.get("text", "") if fc >= 0.5 else "")
                    if PROACTIVE.priority_candidate(fr.get("text", ""), fc, state.speaking_text, cfg) and any(
                            w.get("word") in PRIORITY_WAKE_WORDS and w.get("conf", 0) >= float(cfg.get("priority_wake_min_conf", .85)) for w in fw[:3]):
                        log.info("PRIORITY vosk wake conf=%.2f -> interrupt and capture", fc)
                        interrupt.set()
                        c.ledger.cancel(state.rid)
                        wake = next((w for w in fw[:3] if w.get("word") in PRIORITY_WAKE_WORDS), None)
                        lp.pending = borigin + int((wake.get("start", 0) if wake else 0) * SR) - int(.25 * SR)
                        return
                if lp.brec.AcceptWaveform(bb):
                    ws = json.loads(lp.brec.Result()).get("result", [])
                    if ws:
                        conf = sum(w.get("conf", 0) for w in ws) / len(ws); ph = " ".join(w["word"] for w in ws)
                        echo = any(w["word"].replace("ё", "е") in state.speaking_text for w in ws)
                        partial_free = json.loads(lp.brfree.PartialResult()).get("partial", "")
                        recent_free = lp.free_last[1] if time.monotonic() - lp.free_last[0] < 1.2 else ""
                        corroborated = corroborated_stop(ph, partial_free) or corroborated_stop(ph, recent_free)
                        ok = stop_candidate(ph, conf, echo, cfg) and corroborated
                        log.info("barge-in candidate %r conf=%.2f echo=%s speaking=%s free=%r corroborated=%s -> %s", ph, conf, echo,
                                 c.signals.speaking.is_set(), partial_free or recent_free, corroborated, "STOP" if ok else "ignored")
                        if ok: self.do_stop(ph); return
            except Exception as e: log.info("barge recognizer error: %s", e)
        if cap is None and lp.oww is not None and not state.stop_ack_active and not state.followup_guard:
            if sc < 0.2: lp.barge_armed = True
            elif lp.barge_armed and sc >= cfg["barge_in_threshold"] and not interrupt.is_set():
                log.info("BARGE-IN oww %.2f -> interrupt", sc); interrupt.set()
                c.ledger.cancel(state.rid)
                lp.pending = st + len(x) - int(cfg["wake_prebuffer_s"] * SR)

    def _after_busy(self, lp: Loop) -> bool:
        """First frame after a conversation: reset detectors, then a stop ack or the interrupting turn. True when one started."""
        c = self.c
        lp.was_busy = False; lp.last_end = time.time(); lp.wrec = c.asr.wake_recognizer(); lp.wbase = lp.pos; lp.wake_check = None
        lp.clap.events = []; lp.clap.cur = None
        if lp.oww is not None: lp.oww.reset()
        lp.cfg = c.config.load(); c.state.rid = None
        if c.state.stop_pending:
            c.state.stop_pending = False; lp.pending = None; self.start("stop_ack", text=""); return True
        if lp.pending is not None:
            pre = frames_after(lp.ring, lp.pending); lp.pending = None; lp.barge_armed = False
            self.start("wake_word", pre=pre, skip_s=0.0); return True
        return False

    def _while_sleeping(self, lp: Loop, st: int, i16: np.ndarray) -> None:
        """Sleep: no clap, no wake word, no follow-ups. Only a strict «Джарвис, проснись»."""
        c, cfg = self.c, lp.cfg
        lp.wake_check = None
        if lp.srec is None: lp.srec = c.asr.sleep_recognizer(); lp.sbase = st
        if not lp.srec.AcceptWaveform(i16.tobytes()): return
        ws = json.loads(lp.srec.Result()).get("result", [])
        said = " ".join(w.get("word", "") for w in ws)
        min_conf = GATE.setting(cfg, "sleep_wake_min_conf")
        if SLEEP.is_wake_phrase(said) and min(w.get("conf", 0) for w in ws) >= 0.9:
            a = lp.sbase + int((ws[0]["start"] - 0.45) * SR); b = lp.sbase + int((ws[-1]["end"] + 0.3) * SR)
            if c.asr.verify_wake(lp.ring, a, b, cfg, need=("проснись",), min_conf=min_conf):
                c.sleep.get().stop("phrase"); lp.srec = None
                self.start("sleep_end", text="")
        elif said == SLEEP.HINT_WORD and ws and ws[0].get("conf", 0) >= 0.9 and self.conversation.sleep_hint_due(cfg):
            a = lp.sbase + int((ws[0]["start"] - 0.45) * SR); b = lp.sbase + int((ws[-1]["end"] + 0.3) * SR)
            if c.asr.verify_wake(lp.ring, a, b, cfg, min_conf=min_conf) and c.speaker.owner_confirmed(lp.ring, b, cfg):
                c.state.sleep_hint_at = time.time(); self.start("sleep_hint", text="")

    def _detect_wake(self, lp: Loop, x: np.ndarray, st: int, i16: np.ndarray, sc: float) -> None:
        """Clap, openWakeWord and the Vosk «джарвис» grammar; a weak hit is re-checked by free recognition."""
        c, cfg = self.c, lp.cfg
        trig: str | None = None; frm: int | None = None; skip = 0.0
        if cfg["clap_enabled"] and lp.clap.feed(x, st, cfg): trig = "clap"
        if cfg["wake_word_enabled"] and not trig:
            if sc >= cfg["oww_threshold"] and lp.wake_check is None:
                log.info("oww score %.2f", sc)
                frm = st + len(x) - int(cfg["wake_prebuffer_s"] * SR)
                if sc >= float(GATE.setting(cfg, "oww_strong_threshold")):
                    if c.speaker.ok(lp.ring, lp.pos, cfg): trig = "wake_word"
                else: lp.wake_check = {"a": frm, "b": lp.pos + int(0.3 * SR), "frm": frm, "src": "oww"}
            if lp.wrec.AcceptWaveform(i16.tobytes()):
                res = json.loads(lp.wrec.Result())
                ws = [w for w in res.get("result", []) if w.get("word") == "джарвис"]
                if ws and ws[0].get("conf", 0) >= cfg["vosk_wake_min_conf"]:
                    if not trig and (lp.wake_check is None or lp.wake_check["src"] == "oww"):
                        log.info("vosk wake candidate conf %.2f", ws[0]["conf"])
                        lp.wake_check = {"a": lp.wbase + int((ws[0]["start"] - float(GATE.setting(cfg, "wake_verify_pre_s"))) * SR),
                                         "b": lp.wbase + int((ws[-1]["end"] + float(GATE.setting(cfg, "wake_verify_post_s"))) * SR),
                                         "frm": lp.wbase + int(ws[-1]["end"] * SR) - int(VOSK_WAKE_TAIL_S * SR), "src": "vosk"}
                elif ws: log.info("vosk wake rejected conf %.2f", ws[0].get("conf", 0))
            if not trig and lp.wake_check is not None and lp.pos >= lp.wake_check["b"]:
                wc, lp.wake_check = lp.wake_check, None
                if c.asr.verify_wake(lp.ring, wc["a"], wc["b"], cfg) and c.speaker.ok(lp.ring, wc["b"], cfg):
                    trig = "wake_word"; frm = wc["frm"]; skip = VOSK_WAKE_SKIP_S if wc["src"] == "vosk" else 0.0
        if trig and time.time() - lp.last_end > cfg["cooldown_s"]:
            lp.barge_armed = False
            if trig == "clap": self.start("clap", text="")
            else:
                assert frm is not None  # every wake trigger sets its start frame
                pre = frames_after(lp.ring, frm)
                self.start("wake_word", pre=pre, skip_s=skip)
