"""One conversation: a turn routed to a command or the server, then follow-up turns until silence.

Implements jarvis.commands.base.Services for the command handlers.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any

import jarvis_codemode as CODE
import jarvis_dialog as DIALOG
import jarvis_gate as GATE
import jarvis_sleep as SLEEP
import jarvis_speed as SPEED
from jarvis.adapters.audio import Capture
from jarvis.adapters.status_cache import StatusCache
from jarvis.app.components import Components
from jarvis.commands import registry as COMMANDS
from jarvis.commands.base import Alias, CommandContext
from jarvis.core.followup import FollowupSettings
from jarvis.core.matching import filler_only, followup_echo, natural_status_alias, norm_phrase, pure_wait_filler
from jarvis.core.phrases import Picker
from jarvis.core.ports import Config
from jarvis.core.routing import match_alias
from jarvis.core.state import ListenerState, Mode
from jarvis.core.wake import strip_wake

log = logging.getLogger("jarvis")
SERVER_DOWN_PHRASE = "Сервер не отвечает, сэр. Локальные команды работают."
SERVER_SLOW_PHRASE = "Сервер пока молчит, сэр. Подожду ещё немного."
SLEEP_END_PHRASE = "Я снова на связи, сэр."
NO_REPLY_PHRASE = "Ответ не пришёл, сэр. Попробуйте ещё раз позже."
SEND_FAILED_PHRASE = "Не получилось отправить запрос, сэр."
STILL_WORKING_PHRASE = "Ответ ещё готовится, сэр."
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

    def pick(self, cfg: Config, key: str) -> str: return self.c.picker.pick(cfg, key)
    def controller(self) -> Any: return self.c.controller.get()
    def sleep(self) -> Any: return self.c.sleep.get()
    def proactive(self) -> Any: return self.c.proactive.get()

    def capture(self, cap: Capture, cfg: Config, nospeech_s: float, skip_s: float = 0.0, max_s: float | None = None,
                wake_pause_s: float | None = None) -> tuple[str, float, str]:
        return self.c.asr.capture(cap, cfg, nospeech_s, skip_s, max_s=max_s, wake_pause_s=wake_pause_s)

    def perf(self, event: str, **meta: Any) -> None:
        self.c.state.perf(event, **meta)

    # ------------------------------------------------------------ server round trip
    def ask_server(self, text: str, cfg: Config, trig: str, test: bool, ack: str | None = None, listener_ack: str | None = None,
                   kind: str | None = None, extra_payload: dict[str, Any] | None = None) -> None:
        """POST the phrase to the server while the acknowledgement plays, then speak the outbox replies."""
        st, interrupt = self.c.state, self.c.signals.interrupt
        trace = st.trace
        rid = trace.rid if trace is not None else str(uuid.uuid4()); res: list[Any] = []; st.rid = rid
        chosen_ack = ack if ack is not None else (self.pick(cfg, "ack_server") or cfg.get("fast_ack", "Сейчас, сэр."))
        acknowledged = chosen_ack if listener_ack is None else listener_ack
        kind = kind or ("status" if natural_status_alias(text) else "free")
        log.info("FREE -> webhook rid=%s kind=%s listener_ack=%r: %r", rid, kind, acknowledged, text)
        call = self.c.transport.call
        th = threading.Thread(target=lambda: res.append(call(rid, text, trig, cfg, test, listener_ack=acknowledged, kind=kind, trace=trace,
                                                             extra_payload=extra_payload)), daemon=True)
        th.start()
        self.perf("ack_start")
        self.say(chosen_ack, cfg, role="ack")
        while th.is_alive() and not interrupt.is_set(): th.join(0.1)
        if interrupt.is_set():
            self.c.ledger.cancel(rid); log.info("webhook request abandoned rid=%s", rid); return
        if res and res[0]: self.wait_replies(rid, cfg, listener_ack=acknowledged, kind=kind)
        else: self.say(SEND_FAILED_PHRASE, cfg)

    def wait_replies(self, rid: str, cfg: Config, listener_ack: str = "", kind: str = "free") -> bool:
        st, ledger, outbox, interrupt = self.c.state, self.c.ledger, self.c.outbox, self.c.signals.interrupt
        t0 = time.time(); n = 1; fillers = 0; st.rid = rid
        real_data_seen = False; server_seen = False; slow_noticed = False
        was_down = ledger.recently_down(cfg, t0)

        def speak_part(txt: str) -> None:
            nonlocal real_data_seen
            if GATE.is_silent_reply(txt):
                if txt.strip(): log.info("server asked for silence rid=%s", rid)
                return
            if listener_ack and not real_data_seen and pure_wait_filler(txt):
                log.info("skipped redundant server filler rid=%s: %r", rid, txt); return
            real_data_seen = True
            if kind.startswith("clipboard_") or kind in CODE.PRIVATE_KINDS: self.say_reply(txt, cfg, private=True)
            else: self.say_reply(txt, cfg)

        final = outbox.final(rid)
        while time.time() - t0 < cfg["reply_timeout_s"]:
            outbox.signal.clear()
            if not server_seen and (os.path.exists(final) or os.path.exists(outbox.part(rid, n))):
                server_seen = True; ledger.down_since = None
            el = time.time() - t0
            if not server_seen and was_down and el > float(cfg.get("server_down_wait_s", 45)):
                # Server already failed recently: do not hang for the full timeout again.
                ledger.cancel(rid); ledger.down_since = time.time()
                log.warning("server still silent rid=%s after %.0fs (down since earlier) -> local fallback", rid, el)
                self.say(SERVER_DOWN_PHRASE, cfg); return False
            if not server_seen and not was_down and not slow_noticed and el > float(cfg.get("server_notice_s", 90)):
                slow_noticed = True; log.info("server silent rid=%s after %.0fs -> notice", rid, el)
                self.say(SERVER_SLOW_PHRASE, cfg)
            # An initial acknowledgement is enough. No second "checking" announcement.
            if not listener_ack and not real_data_seen and fillers == 0 and time.time() - t0 > max(12.0, float(cfg.get("wait_filler_s", 12))) \
                    and not os.path.exists(final) and not os.path.exists(outbox.part(rid, n)):
                fillers += 1; self.say(STILL_WORKING_PHRASE, cfg)
            if interrupt.is_set():
                ledger.cancel(rid); log.info("reply wait for %s abandoned (interrupted), rid cancelled", rid); return False
            part = outbox.part(rid, n)
            if os.path.exists(part) or os.path.exists(final): self.perf("first_server_file")
            if os.path.exists(part) and outbox.ready(part):
                self.perf("first_server_file")
                txt = outbox.read(part); outbox.log_arrival(part, rid, "part " + str(n), txt, t0)
                outbox.move_done(part); speak_part(txt); n += 1; continue
            if os.path.exists(final) and outbox.ready(final, allow_empty=real_data_seen or outbox.file_age(final) >= 0.6):
                self.perf("first_server_file")
                while os.path.exists(outbox.part(rid, n)):
                    p = outbox.part(rid, n); t = outbox.read(p); outbox.move_done(p); log.info("outbox part %d (%d chars)", n, len(t)); speak_part(t); n += 1
                txt = outbox.read(final); outbox.log_arrival(final, rid, "final", txt, t0); outbox.move_done(final)
                speak_part(txt); return True
            outbox.signal.wait(cfg)
        log.warning("reply timeout for %s", rid)
        if not server_seen and not real_data_seen:
            ledger.down_since = time.time(); ledger.cancel(rid)
            log.warning("server marked unresponsive (no outbox file for rid=%s)", rid)
            self.say(SERVER_DOWN_PHRASE, cfg); return False
        self.say(NO_REPLY_PHRASE, cfg)
        return False

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

    def handle_turn(self, trig: str, cap: Capture | None, text: Any, test: bool, skip_s: float) -> None:
        c, st, interrupt, choose = self.c, self.c.state, self.c.signals.interrupt, self.c.router.choose
        cfg = c.config.load()
        try:
            log.info("TRIGGER %s%s", trig, " (test)" if test else "")
            if self._event_turn(trig, text, cfg, test): return
            ok = True
            if text is None:
                pause = float(cfg.get("wake_ack_after_s", DIALOG.DEFAULTS["wake_ack_after_s"])) if trig == "wake_word" else None
                text, conf, g = ("", 0.0, "") if cap is None else self.capture(cap, cfg, float(cfg["phrase_wait_s"]), skip_s, wake_pause_s=pause)
                c.fsm.to(Mode.PROCESSING, "captured")
                text, ok = choose(text, conf, g, cfg)
                if st.dropped: return
            else:
                text = strip_wake(norm_phrase(text))
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
                # Never "sorry, I did not catch that": unclear input is dropped silently.
                log.info("not understood -> silent: %r", text); return
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
            st.trace = trace or SPEED.Trace(trig)
            st.trace.meta["test"] = bool(test)
            while True:
                st.reply_parts = []
                st.followup_eligible = False
                serial = st.speech_serial
                self.handle_turn(trig, cap, text, test, skip_s)
                st.trace.finish("interrupted" if interrupt.is_set() else "done")
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
                st.trace = SPEED.Trace("followup")
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
