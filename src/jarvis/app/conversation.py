"""One conversation: a turn routed to a command or the server, then follow-up turns until silence.

Implements jarvis.commands.base.Services for the command handlers.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from jarvis.core import codemode as CODE
from jarvis.core import dialog as DIALOG
from jarvis.core import sleep as SLEEP
from jarvis.adapters.audio import Capture
from jarvis.adapters.status_cache import StatusCache
from jarvis.app import server_jobs as SERVER_JOBS
from jarvis.app.components import Components
from jarvis.app.server_jobs import BUSY_PHRASE
from jarvis.commands import registry as COMMANDS
from jarvis.commands.base import Alias, CommandContext
from jarvis.commands.controller import Controller
from jarvis.core.followup import FollowupSettings
from jarvis.core.matching import filler_only, followup_echo, natural_status_alias, norm_phrase
from jarvis.core.perf import Trace
from jarvis.core.phrases import Picker
from jarvis.core.ports import Config, Laptop
from jarvis.core.routing import match_alias
from jarvis.core.state import ListenerState, Mode, ServerJob
from jarvis.core.wake import strip_wake

log = logging.getLogger("jarvis")
SLEEP_END_PHRASE = "Я снова на связи, сэр."
TIMER_DONE_PHRASE = "Сэр, время вышло."


class Conversation:
    def __init__(self, c: Components) -> None:
        self.c = c
        COMMANDS.load_builtin()

    # ------------------------------------------------------------ Services for command handlers
    @property
    def state(self) -> ListenerState: return self.c.state
    @property
    def status(self) -> StatusCache: return self.c.status
    @property
    def picker(self) -> Picker: return self.c.picker

    def say(self, text: str, cfg: Config, role: str = "reply", private: bool = False) -> bool:
        return self.c.voice.say(text, cfg, role=role, private=private)

    def say_reply(self, text: str, cfg: Config, private: bool = False) -> None:
        """Speak a server or data reply; retry while the speaker is busy (up to 30 s, until interrupted)."""
        t0 = time.time()
        while not self.say(text, cfg, private=private):
            if self.c.signals.interrupt.is_set() or time.time() - t0 > 30: return
            time.sleep(3)

    def stop_reply(self) -> None:
        """«Стоп» as a command: cancel the server reply a barge-in has just cut."""
        self.c.jobs.cancel_paused("stop command")

    def pick(self, cfg: Config, key: str) -> str: return self.c.picker.pick(cfg, key)
    def controller(self) -> Controller: return self.c.controller.get()
    def laptop(self) -> Laptop: return self.c.laptop
    def sleep(self) -> Any: return self.c.sleep.get()
    def proactive(self) -> Any: return self.c.proactive.get()

    def capture(self, cap: Capture, cfg: Config, nospeech_s: float, skip_s: float = 0.0, max_s: float | None = None,
                wake_pause_s: float | None = None) -> tuple[str, float, str]:
        return self.c.asr.capture(cap, cfg, nospeech_s, skip_s, max_s=max_s, wake_pause_s=wake_pause_s)

    def perf(self, event: str, **meta: Any) -> None:
        self.c.state.perf(event, **meta)

    # ------------------------------------------------------------ server requests
    def ask_server(self, text: str, cfg: Config, trig: str, test: bool, ack: str | None = None, listener_ack: str | None = None,
                   kind: str | None = None, extra_payload: dict[str, Any] | None = None) -> None:
        """Hand the phrase to the background worker and speak the acknowledgement; the conversation ends here.

        The answer is spoken later by a ``server_reply`` turn, so local commands work meanwhile."""
        st, interrupt = self.c.state, self.c.signals.interrupt
        trace = st.trace
        rid = trace.rid if trace is not None else str(uuid.uuid4())
        chosen_ack = ack if ack is not None else (self.pick(cfg, "ack_server") or cfg.get("fast_ack", "Сейчас, сэр."))
        acknowledged = chosen_ack if listener_ack is None else listener_ack
        kind = kind or ("status" if natural_status_alias(text) else "free")
        job = ServerJob(rid=rid, text=text, kind=kind, created=time.time(), trigger=trig, listener_ack=acknowledged, test=test,
                        extra_payload=extra_payload, private=kind.startswith("clipboard_") or kind in CODE.PRIVATE_KINDS, trace=trace)
        st.followup_eligible = False
        if not self.c.jobs.submit(job, cfg):
            self.say(BUSY_PHRASE, cfg); return
        st.trace = None  # the job owns the latency trace now; its reply turn finishes it
        log.info("FREE -> server job rid=%s kind=%s listener_ack=%r: %r", rid, kind, acknowledged, text)
        if trace is not None: trace.mark("ack_start")
        self.say(chosen_ack, cfg, role="ack")
        if interrupt.is_set() and st.stop_pending: self.c.jobs.cancel(job, "stop during the acknowledgement")

    def speak_job(self, job: ServerJob, cfg: Config) -> None:
        """Speak the ready parts of ``job``, waiting briefly for the next one; «стоп» cancels it (Listener.do_stop),
        any other barge-in only pauses it: the cut part is spoken again in the next reply turn."""
        st, interrupt, jobs = self.c.state, self.c.signals.interrupt, self.c.jobs
        gap = float(cfg.get("server_reply_gap_s", SERVER_JOBS.DEFAULTS["server_reply_gap_s"]))
        jobs.speaking = job
        if jobs.paused is job: jobs.paused = None
        try:
            while not job.cancelled:
                part = job.pop(time.time())
                if part is None:
                    if job.finished or not job.arrived.wait(gap): break
                    continue
                if not self.say(part.text, cfg, private=job.private):
                    if interrupt.is_set() and not job.cancelled: job.requeue(part); jobs.paused = job
                    break
                if part.data:
                    job.spoken.append(part.text)
                    st.last_reply, st.last_reply_private = job.last_reply, job.private
        finally:
            jobs.speaking = None
        st.followup_eligible = job.done and not job.cancelled and not interrupt.is_set()

    def request_morning(self, job: dict[str, Any], cfg: Config, test: bool = False) -> None:
        extra = {k: v for k, v in job.items() if k not in ("request_id", "kind", "date", "attempts", "retry_at")}
        text = "Составь короткий утренний брифинг по моим свежим данным. Ответ только в указанном proactive outbox, без вводного подтверждения."
        result: Any = False
        try: result = self.c.transport.call(job["request_id"], text, "presence", cfg, test, listener_ack="", kind="morning_briefing", extra_payload=extra)
        finally:
            if not test: self.proactive().morning_result(job, result, cfg)
        log.info("morning briefing POST date=%s ok=%s", job.get("local_date"), bool(result))

    # ------------------------------------------------------------ turns
    def run_alias(self, al: Alias, text: str, cfg: Config, trig: str, test: bool) -> None:
        COMMANDS.dispatch(CommandContext(text, cfg, trig, test, self), al)

    def sleep_hint_due(self, cfg: Config) -> bool:
        """A bare «Джарвис» during sleep gets at most one spoken hint per interval."""
        if not cfg.get("sleep_hint_enabled", SLEEP.DEFAULTS["sleep_hint_enabled"]): return False
        gap = float(cfg.get("sleep_hint_interval_s", SLEEP.DEFAULTS["sleep_hint_interval_s"]))
        return time.time() - float(self.c.state.sleep_hint_at or 0) >= gap

    def _event_turn(self, trig: str, text: Any, cfg: Config, test: bool) -> bool:
        """Turns started by the listener itself, not by speech. True when trig was one of them."""
        st, interrupt = self.c.state, self.c.signals.interrupt
        if trig == "stop_ack":
            self.perf("route", route="stop_ack")
            st.stop_ack_active = True
            ack = self.pick(cfg, "ack_stop"); log.info("stop ack begin: %s interrupt=%s", ack, interrupt.is_set())
            result = self.say(ack, cfg, role="stop_ack")
            log.info("stop ack complete: played=%s", result); return True
        if trig == "proactive":
            item = text if isinstance(text, dict) else {}
            self.perf("route", route="proactive_" + str(item.get("kind", "file")))
            try:
                if item.get("expires") is None or time.time() < item["expires"]:
                    st.followup_eligible = True
                    self.say(item.get("text", ""), cfg)
            finally:
                if not test: self.proactive().complete(item, interrupt.is_set())
            return True
        if trig == "server_reply":
            self.perf("route", route="server_reply")
            if isinstance(text, ServerJob): self.speak_job(text, cfg)
            return True
        if trig == "sleep_end":
            self.perf("route", route="sleep_end"); self.say(SLEEP_END_PHRASE, cfg); return True
        if trig == "sleep_hint":
            self.perf("route", route="sleep_hint"); st.followup_eligible = False
            self.say(SLEEP.hint_phrase(self.sleep().remaining()), cfg); return True
        if trig == "timer_fire":
            self.perf("route", route="timer_fire")
            notice = text if isinstance(text, dict) else {}
            try:
                self.c.voice.beep()
                if notice.get("kind") == "timer": self.c.voice.beep()
            except Exception: pass
            self.say(notice.get("label") or TIMER_DONE_PHRASE, cfg); return True
        return False

    def not_understood(self, trig: str, cfg: Config, reason: str, text: str) -> None:
        """The name was heard but the phrase dropped: a short low tone instead of silence (never a spoken
        «не расслышал»); follow-ups and speech without the name stay silent."""
        st = self.c.state; now = time.monotonic()
        if not DIALOG.reject_beep_due(cfg, trig, st.reject_beep_at, now):
            log.info("not understood -> silent (%s): %r", reason, text); return
        st.reject_beep_at = now
        log.info("not understood -> beep (%s): %r", reason, text)
        try: self.c.voice.beep_reject()
        except Exception as e: log.info("reject beep failed: %s", type(e).__name__)

    def handle_turn(self, trig: str, cap: Capture | None, text: Any, test: bool, skip_s: float) -> None:
        c, st, interrupt, choose = self.c, self.c.state, self.c.signals.interrupt, self.c.router.choose
        cfg = c.config.load()
        try:
            log.info("TRIGGER %s%s", trig, " (test)" if test else "")
            if self._event_turn(trig, text, cfg, test): return
            ok = True; st.drop_reason = ""
            if text is None:
                pause = float(cfg.get("wake_ack_after_s", DIALOG.DEFAULTS["wake_ack_after_s"])) if trig == "wake_word" else None
                text, conf, g = ("", 0.0, "") if cap is None else self.capture(cap, cfg, float(cfg["phrase_wait_s"]), skip_s, wake_pause_s=pause)
                c.fsm.to(Mode.PROCESSING, "captured")
                text, ok = choose(text, conf, g, cfg)
                if st.dropped: self.not_understood(trig, cfg, st.drop_reason, text); return
            else:
                text = strip_wake(norm_phrase(text), c.asr.names(cfg))
                if trig != "followup":
                    st.last_input_conf = 1.0
                    st.last_input_end = None
            if not text:
                self.say(self.pick(cfg, "ack_wake"), cfg, role="wake")
                if interrupt.is_set(): return
                cap2 = Capture(); st.capture = cap2; c.fsm.to(Mode.LISTENING, "after wake ack")
                text, conf, g = self.capture(cap2, cfg, float(cfg["followup_listen_s"]))
                c.fsm.to(Mode.PROCESSING, "captured")
                raw2 = text
                text, ok = choose(text, conf, g, cfg)
                if not text and (not g or filler_only(raw2)):
                    log.info("no follow-up phrase"); return
            if interrupt.is_set(): return
            if not ok or not text:
                self.not_understood(trig, cfg, st.drop_reason or ("empty" if not text else "rejected"), text); return
            self.perf("recognized")
            confirmation = self.controller().confirmation(text, trig, st.last_input_conf, heard_at=st.last_input_end)
            al = ({"name": "shutdown_confirmation", "action": "quick2", "cmd": "shutdown_confirm", **confirmation}
                  if confirmation is not None else match_alias(text, cfg))
            self.perf("route", route=(al.get("name", "local") if al else "webhook"))
            st.followup_eligible = not (al and al.get("action") == "stop")
            if al: self.run_alias(al, text, cfg, trig, test)
            else: self.ask_server(text, cfg, trig, test)
        except Exception as e:
            log.exception("handle error: %s", e)
        finally:
            st.capture = None; st.stop_ack_active = False

    def handle(self, trig: str, cap: Capture | None, text: Any, test: bool, skip_s: float, trace: Any = None) -> None:
        """Own the entire short conversation; only silence/stop/limit returns to wake mode."""
        c, st, interrupt = self.c, self.c.state, self.c.signals.interrupt
        try:
            turns = 0
            c.fsm.to(Mode.LISTENING if (text is None and cap is not None) else Mode.PROCESSING, trig)
            st.trace = trace or Trace(trig)
            st.trace.meta["test"] = bool(test)
            while True:
                st.reply_parts = []
                st.followup_eligible = False
                serial = st.speech_serial
                self.handle_turn(trig, cap, text, test, skip_s)
                if st.trace is not None: st.trace.finish("interrupted" if interrupt.is_set() else "done")
                cfg = c.config.load(); fs = FollowupSettings.from_cfg(cfg)
                if interrupt.is_set() or not fs.enabled: break
                if not st.followup_eligible or st.speech_serial == serial: break
                if turns >= fs.max_turns:
                    log.info("follow-up turn limit -> wake mode"); break
                spoken = st.last_spoken
                window = fs.window_for(spoken)
                ctl = c.controller.peek()
                if ctl is not None and ctl.pending_shutdown:
                    window = max(0.0, ctl.pending_shutdown["expires"] - ctl.clock())
                if window <= 0: break
                guard = fs.echo_guard_s
                st.followup_guard = True
                # Based on actual playback end, not synthesis start or webhook acknowledgement.
                delay = max(0.0, st.last_spoken_end + guard - time.monotonic())
                if interrupt.wait(delay): break
                log.info("follow-up open window_s=%.1f guard_s=%.2f question=%s turn=%d", window, guard, spoken.rstrip().endswith("?"), turns + 1)
                st.trace = Trace("followup")
                st.trace.meta["test"] = bool(test)
                cap = Capture(); st.capture = cap; st.followup_guard = False; c.fsm.to(Mode.FOLLOWUP, "window")
                text, conf, grammar = self.capture(cap, cfg, window, max_s=window + float(cfg["phrase_max_s"]))
                if interrupt.is_set(): break
                if text and conf < fs.min_conf:
                    rescued = c.router.followup_rescue(text, grammar, cfg)
                    if rescued: log.info("follow-up grammar wins: %r (free %r conf %.2f)", rescued, text, conf); text, conf = rescued, 1.0
                if not text or conf < fs.min_conf:
                    st.trace.finish("silence")
                    log.info("follow-up close: silence/low confidence text=%r conf=%.2f", text, conf); break
                if followup_echo(text, spoken):
                    st.trace.finish("echo")
                    log.info("follow-up close: likely speaker echo %r", text); break
                chosen, ok = c.router.choose(text, conf, grammar, cfg, followup=True)
                if not ok or not chosen:
                    st.trace.finish("fragment")
                    log.info("follow-up close: fragment/garbage %r", text); break
                text = chosen; cap = None; skip_s = 0.0; trig = "followup"; turns += 1; c.fsm.to(Mode.PROCESSING, "follow-up")
                log.info("follow-up accepted conf=%.2f text=%r", conf, text)
        except Exception:
            log.exception("conversation handler error")
        finally:
            if st.trace is not None: st.trace.finish("interrupted" if interrupt.is_set() else "done")
            st.trace = None
            ctl = c.controller.peek()
            if ctl is not None: ctl.clear_pending()
            st.capture = None; st.followup_guard = False
            st.stop_ack_active = False; c.fsm.to(Mode.IDLE, "conversation over"); c.signals.busy.clear()
