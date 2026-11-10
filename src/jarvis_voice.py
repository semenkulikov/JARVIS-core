# Jarvis voice assistant 3.18.0
import os
for _k, _v in {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "1"}.items(): os.environ.setdefault(_k, _v)
import json, time, uuid, queue, threading, logging, subprocess, datetime, re, collections, shlex
from logging.handlers import RotatingFileHandler
import numpy as np
import sounddevice as sd

import jarvis_paths as PATHS
BASE = str(PATHS.HOME)
LOGDIR = str(PATHS.log_dir())
os.makedirs(LOGDIR, exist_ok=True)
os.makedirs(os.path.join(BASE, "cache"), exist_ok=True)
TEST_TRIGGER = os.path.join(BASE, "test_trigger")
STOP_FILE = os.path.join(BASE, "stop")

log = logging.getLogger("jarvis")
log.setLevel(logging.INFO)
if not log.handlers:
    h = RotatingFileHandler(os.path.join(LOGDIR, "jarvis_voice.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)

import jarvis_text as JT
import laptop as LP
import jarvis_commands as QUICK
import jarvis_proactive as PROACTIVE
import jarvis_runtime as RUNTIME
import jarvis_audio as AUDIO
import jarvis_speaker as SPEAKER
import jarvis_gate as GATE
import jarvis_sleep as SLEEP
import jarvis_codemode as CODE
import jarvis_dialog as DIALOG
import jarvis_tasks as TASKS
import jarvis_registry as REGISTRY
from jarvis.core.wake import (PRIORITY_WAKE_WORDS, VOSK_WAKE_TAIL_S, VOSK_WAKE_SKIP_S, strip_wake)
from jarvis.adapters.audio import AGC, CHUNK, SR, Capture, ClapDetector, MicInput, frames_after, pick_device, ring_audio
from jarvis.adapters.tts import Voice, split_text
from jarvis.adapters.transport import WebhookTransport
from jarvis.adapters.outbox import Outbox, read_text
from jarvis.adapters.status_cache import StatusCache
from jarvis.adapters.asr_vosk import VoskASR
from jarvis.adapters.process import mem_info, trim_memory
from jarvis.core.schedule import workout_summary
from jarvis.core.routing import Router, match_alias
from jarvis.core.state import ListenerFSM, ListenerState, Mode, RequestLedger, Signals
from jarvis.app import settings as SETTINGS
from jarvis.app.settings import DEFAULTS
from jarvis.core.phrases import Picker, all_phrases, smalltalk_reply
from jarvis.core.followup import FollowupSettings
from jarvis.core.matching import (norm_phrase as _norm_phrase, natural_status_alias, filler_only,
                                  pure_wait_filler, followup_echo, corroborated_stop, stop_candidate)
CMDS = None
def command_controller():
    global CMDS
    if CMDS is None: CMDS = QUICK.Controller(BASE)
    return CMDS

import jarvis_speed as SPEED
OUTBOX = Outbox(os.path.join(BASE, "outbox")); OUTBOX.ensure()

def perf(event, **meta):
    STATE.perf(event, **meta)


CONFIG = SETTINGS.config_store(BASE)
load_cfg = CONFIG.load
PICKER = Picker(DEFAULTS)
pick = PICKER.pick

MIC = MicInput()
SIGNALS = Signals()
busy, speaking, interrupt = SIGNALS.busy, SIGNALS.speaking, SIGNALS.interrupt
FSM = ListenerFSM()
STATE = ListenerState()
ROUTER = Router(STATE, lambda: CMDS is not None and bool(getattr(CMDS, "pending_shutdown", None)))
choose, followup_rescue = ROUTER.choose, ROUTER.followup_rescue
LEDGER = RequestLedger()
ASR = VoskASR(STATE)
capture_phrase, verify_wake = ASR.capture, ASR.verify_wake
TRANSPORT = WebhookTransport(SIGNALS, LEDGER)
call_webhook = TRANSPORT.call
PLAYER = AUDIO.Player(sd)
VOICE = Voice(BASE, STATE, SIGNALS, FSM, PLAYER)
say, get_audio, beep = VOICE.say, VOICE.get_audio, VOICE.beep
SLEEP_STATE = None
WAKE_FILE = os.path.join(BASE, SLEEP.WAKE_FILE)
SLEEP_END_PHRASE = "Я снова на связи, сэр."
def sleep_state():
    global SLEEP_STATE
    if SLEEP_STATE is None: SLEEP_STATE = SLEEP.SleepState(os.path.join(BASE, "cache", "sleep.json"))
    return SLEEP_STATE













def precache(cfg):
    # Warm the first server ack before RUAccent has finished loading as well.
    try:
        get_audio(cfg.get("fast_ack", "Сейчас, сэр."), cfg)
        log.info("fast ack cache ready (initial)")
    except Exception as e: log.warning("fast ack warmup: %s", type(e).__name__)
    JT.init_accentizer(cfg, BASE)
    cfg = load_cfg(); pronunciation_audit = []
    for t in all_phrases(cfg) + ["Блокирую, сэр.", "Сэр, время вышло.", "Таймер отменён, сэр.", "Вебхук не настроен, сэр.", "Не получилось отправить запрос, сэр.",
              "Ответ не пришёл, сэр. Попробуйте ещё раз позже.", SERVER_DOWN_PHRASE, SERVER_SLOW_PHRASE, "Хорошо, сэр.", "Свежих данных нет, сэр, запрашиваю.", "Не нашёл приложение, сэр."]:
        pronunciation_audit.append({"text": t, "normalized": JT.normalize(t, cfg)})
        for _attempt in range(10):
            try:
                for chunk in split_text(t, int(cfg.get("tts_chunk_chars",170))): get_audio(chunk, cfg)
                break
            except Exception as e: log.info("precache retry %s: %s", t, e); time.sleep(10)
    try:
        with open(os.path.join(BASE, "cache", "pronunciation_audit_v312.json"), "w", encoding="utf-8") as f:
            json.dump(pronunciation_audit, f, ensure_ascii=False, indent=2)
    except Exception as e: log.warning("pronunciation audit save failed: %s", type(e).__name__)
    log.info("precache done (%s, ruaccent=%s, audited_phrases=%d)", cfg.get("tts_engine"), JT.accent_state(), len(pronunciation_audit))
    if cfg.get("template_precache", True):
        templates = SPEED.template_phrases(cfg, JT)
        for phrase in templates:
            if os.path.exists(STOP_FILE): break
            # Do not queue background synthesis ahead of an active conversation.
            while busy.is_set() and not os.path.exists(STOP_FILE): time.sleep(0.1)
            if os.path.exists(STOP_FILE): break
            try: get_audio(phrase, cfg)
            except Exception as e: log.info("template cache skipped: %s", type(e).__name__)
        log.info("template precache done (%d bounded time/number sentences)", len(templates))
    trim_memory()















def say_reply(txt, cfg, private=False):
    t0 = time.time()
    while not say(txt, cfg, private=private):
        if interrupt.is_set() or time.time() - t0 > 30: return
        time.sleep(3)





SERVER_DOWN_PHRASE = "Сервер не отвечает, сэр. Локальные команды работают."
SERVER_SLOW_PHRASE = "Сервер пока молчит, сэр. Подожду ещё немного."


def wait_replies(rid, cfg, listener_ack="", kind="free"):
    t0 = time.time(); n = 1; fillers = 0; STATE.rid = rid
    real_data_seen = False; server_seen = False; slow_noticed = False
    was_down = LEDGER.recently_down(cfg, t0)
    def speak_part(txt):
        nonlocal real_data_seen
        if GATE.is_silent_reply(txt):
            if txt.strip(): log.info("server asked for silence rid=%s", rid)
            return
        if listener_ack and not real_data_seen and pure_wait_filler(txt):
            log.info("skipped redundant server filler rid=%s: %r", rid, txt); return
        real_data_seen = True
        if kind.startswith("clipboard_") or kind in CODE.PRIVATE_KINDS: say_reply(txt,cfg,private=True)
        else: say_reply(txt, cfg)
    final = OUTBOX.final(rid)
    while time.time() - t0 < cfg["reply_timeout_s"]:
        OUTBOX.signal.clear()
        if not server_seen and (os.path.exists(final) or os.path.exists(OUTBOX.part(rid, n))):
            server_seen = True; LEDGER.down_since = None
        el = time.time() - t0
        if not server_seen and was_down and el > float(cfg.get("server_down_wait_s", 45)):
            # Server already failed recently: do not hang for the full timeout again.
            LEDGER.cancel(rid); LEDGER.down_since = time.time()
            log.warning("server still silent rid=%s after %.0fs (down since earlier) -> local fallback", rid, el)
            say(SERVER_DOWN_PHRASE, cfg); return False
        if not server_seen and not was_down and not slow_noticed and el > float(cfg.get("server_notice_s", 90)):
            slow_noticed = True; log.info("server silent rid=%s after %.0fs -> notice", rid, el)
            say(SERVER_SLOW_PHRASE, cfg)
        # An initial acknowledgement is enough. No second "checking" announcement.
        if not listener_ack and not real_data_seen and fillers == 0 and time.time() - t0 > max(12.0, float(cfg.get("wait_filler_s", 12))) \
                and not os.path.exists(final) and not os.path.exists(OUTBOX.part(rid, n)):
            fillers += 1; say("Ответ ещё готовится, сэр.", cfg)
        if interrupt.is_set():
            LEDGER.cancel(rid); log.info("reply wait for %s abandoned (interrupted), rid cancelled", rid); return False
        part = OUTBOX.part(rid, n)
        if os.path.exists(part) or os.path.exists(final): perf("first_server_file")
        if os.path.exists(part) and OUTBOX.ready(part):
            perf("first_server_file")
            txt = OUTBOX.read(part); OUTBOX.log_arrival(part, rid, "part " + str(n), txt, t0)
            OUTBOX.move_done(part); speak_part(txt); n += 1; continue
        if os.path.exists(final) and OUTBOX.ready(final, allow_empty=real_data_seen or OUTBOX.file_age(final) >= 0.6):
            perf("first_server_file")
            while os.path.exists(OUTBOX.part(rid, n)):
                p = OUTBOX.part(rid, n); t = OUTBOX.read(p); OUTBOX.move_done(p); log.info("outbox part %d (%d chars)", n, len(t)); speak_part(t); n += 1
            txt = OUTBOX.read(final); OUTBOX.log_arrival(final, rid, "final", txt, t0); OUTBOX.move_done(final)
            speak_part(txt); return True
        OUTBOX.signal.wait(cfg)
    log.warning("reply timeout for %s", rid)
    if not server_seen and not real_data_seen:
        LEDGER.down_since = time.time(); LEDGER.cancel(rid)
        log.warning("server marked unresponsive (no outbox file for rid=%s)", rid)
        say(SERVER_DOWN_PHRASE, cfg); return False
    say("Ответ не пришёл, сэр. Попробуйте ещё раз позже.", cfg)
    return False

CACHE = StatusCache(os.path.join(BASE, "cache", "status.json"))

# ================= aliases =================








def run_tasks(mode, text, cfg, trig, test):
    """Briefing / what is left / all tasks / Notion: from a fresh snapshot, otherwise from the server."""
    cache, fresh, stamp = CACHE.tasks_snapshot(cfg)
    reply, server_text = TASKS.answer(mode, cache if isinstance(cache, dict) else None, fresh, stamp=stamp)
    log.info("tasks %s -> %s", mode, "cache" if reply else "server")
    if reply: say_reply(reply, cfg); return
    free_phrase(server_text, cfg, trig, test, ack=pick(cfg, "ack_lookup"), kind="free", extra_payload={"intent": "tasks_" + mode})



def run_alias(al, text, cfg, trig, test):
    act = al.get("action", "say"); reply = al.get("reply") or ""
    ack = lambda: say(reply or pick(cfg, "ack_command"), cfg, role="ack")
    log.info("ALIAS %s (%s) <- %r", al.get("name", "?"), act, text)
    if act == "jarvis_sleep":
        STATE.followup_eligible = False
        secs = int(al["seconds"])
        if test: log.info("TEST sleep %ss: no persistent change", secs)
        else: sleep_state().start(secs)
        say(SLEEP.enter_phrase(secs), cfg)
        return
    if act == "awake":
        say(TASKS.AWAKE_REPLY, cfg); return
    if act == "capabilities":
        for line in REGISTRY.log_lines(): log.info("capabilities: %s", line)
        say_reply(REGISTRY.capabilities_phrase(), cfg); return
    if act == "tasks":
        run_tasks(al["mode"], text, cfg, trig, test); return
    if act == "proactive_dnd":
        if test: log.info("TEST DND=%s: no persistent change",al["enabled"])
        else: proactive_manager().set_dnd(al["enabled"])
        say(PROACTIVE.REPLIES[0 if al["enabled"] else 1],cfg)
        return
    if act == "quick2":
        key = DIALOG.ack_key(al); spoken = pick(cfg, key) if key else ""
        # After an instant ack a server fallback must not add a second one.
        fwd_ack = {"ack": "", "listener_ack": spoken} if spoken else {}
        run = lambda speak: command_controller().execute(al,text,cfg,speak,lambda value,**kw:free_phrase(value,cfg,trig,test,**{**fwd_ack, **kw}),
                last_reply=STATE.last_reply,last_private=STATE.last_reply_private,trigger=trig,
                confidence=STATE.last_input_conf,test=test)
        keep = DIALOG.ack_then(say, cfg, spoken, run)
        if not keep: STATE.followup_eligible = False
        return
    if act in ("status", "cache_field"):
        field = al.get("field") if act == "cache_field" else None
        decision, cached, age = CACHE.cached_status(field, cfg)
        log.info("status cache policy=%s field=%s age_h=%s", decision, field or "all", None if age is None else round(age,3))
        if decision == "fresh":
            say_reply(cached, cfg); return
        if decision == "stale":
            spoken = cached + " Это сохранённые данные. Обновляю данные, сэр."
            # Fetch concurrently while the dated snapshot is being read.
            free_phrase(text, cfg, trig, test, ack=spoken, kind="status"); return
        free_phrase(text if field else "статус по задачам", cfg, trig, test, ack=pick(cfg, "ack_status"), kind="status")
    elif act == "time":
        now = datetime.datetime.now(); say(f"Сейчас {JT.time_words(now.hour, now.minute)}, сэр.", cfg)
    elif act == "workout":
        say(workout_summary(cfg), cfg)
    elif act == "smalltalk":
        say(smalltalk_reply(al, PICKER), cfg)
    elif act == "stop":
        say(pick(cfg, "ack_stop"), cfg, role="stop_ack")
    elif act == "key":
        vk = LP.VK[al["key"]]; n = int(al.get("times", 1))
        if test: log.info("TEST: would send vk=0x%X x%d", vk, n)
        else: LP.press(vk, n)
        if not al.get("silent") and al["key"] != "mute": ack()
    elif act == "monitor_off":
        ack()
        if test: log.info("TEST: would turn monitor off")
        else: time.sleep(0.5); LP.monitor_off()
    elif act == "timer":
        secs = LP.parse_duration_s(text)
        if not secs: say("На сколько поставить таймер, сэр?", cfg); return
        LP.TIMERS.add(secs, text)
        say(f"Таймер на {QUICK.duration_label(secs)}, сэр.", cfg)
    elif act == "timer_cancel":
        n = LP.TIMERS.cancel(); say("Таймер отменён, сэр." if n else "Активных таймеров нет, сэр.", cfg)
    elif act == "battery":
        pct, ac = LP.battery()
        if pct is None: say("Не вижу батарею, сэр.", cfg); return
        say(f"Заряд {JT.num_ru(pct)} {JT.plural(pct, 'процент', 'процента', 'процентов')}, " + ("зарядка подключена, сэр." if ac else "работаем от батареи, сэр."), cfg)
    elif act == "temperature":
        t = LP.temperature_c()
        if t is None: say("Датчик температуры сейчас недоступен, сэр.", cfg)
        else: say(f"Температура системы {JT.num_ru(t)} {JT.plural(t, 'градус', 'градуса', 'градусов')}, сэр.", cfg)
    elif act == "open_project":
        rest = " ".join(_norm_phrase(text)); rest = re.sub(r"^.*?проект\w*\s*", "", rest)
        path, score = LP.find_project(rest, lambda w: JT._latin(re.match(r"(?s).+", w)))
        log.info("project match %r -> %s (%.2f)", rest, path, score)
        exe = LP.cursor_exe()
        if not path or score < 0.5: say("Не нашёл такой проект, сэр.", cfg); return
        if not exe: say("Не нашёл Курсор, сэр.", cfg); return
        if test: log.info("TEST: would run %s %s", exe, path)
        else: subprocess.Popen([exe, path], creationflags=0x08000000)
        ack()
    elif act == "open_github":
        url = CACHE.github_url()
        if not url:
            r = LP.recent_repo(); url = LP.remote_url(r) if r else None; log.info("recent repo %s -> %s", r, url)
        if not url: say("Не нашёл репозиторий, сэр.", cfg); return
        if test: log.info("TEST: would open %s", url)
        else: os.startfile(url)
        ack()
    elif act == "open":
        tgt = os.path.expandvars(al.get("target", ""))
        if test: log.info("TEST: would open %s (exists=%s)", tgt, os.path.exists(tgt) or tgt.startswith("http")); ack(); return
        try:
            if not re.match(r"^\w+:", tgt) or re.match(r"^[A-Za-z]:\\", tgt):
                if not os.path.exists(tgt): raise FileNotFoundError(tgt)
            os.startfile(tgt); ack()
        except Exception as e:
            log.warning("open failed %s: %s", tgt, e); say("Не нашёл приложение, сэр.", cfg)
    elif act == "lock":
        ack()
        if test: log.info("TEST: would lock"); return
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif act == "shell":
        ack()
        target = str(al.get("target", "")).strip()
        if test: log.info("TEST: would run %s", target); return
        if not target: return
        subprocess.Popen(shlex.split(target, posix=False), shell=False)
    elif act == "webhook":
        free_phrase(al.get("target") or text, cfg, trig, test, ack=reply or None)
    else:
        say(reply, cfg)

def free_phrase(text, cfg, trig, test, ack=None, listener_ack=None, kind=None, extra_payload=None):
    trace = STATE.trace
    rid = trace.rid if trace is not None else str(uuid.uuid4()); res = []; STATE.rid = rid
    chosen_ack = ack if ack is not None else (pick(cfg, "ack_server") or cfg.get("fast_ack", "Сейчас, сэр."))
    acknowledged = chosen_ack if listener_ack is None else listener_ack
    kind = kind or ("status" if natural_status_alias(text) else "free")
    log.info("FREE -> webhook rid=%s kind=%s listener_ack=%r: %r", rid, kind, acknowledged, text)
    th = threading.Thread(target=lambda: res.append(call_webhook(rid, text, trig, cfg, test, listener_ack=acknowledged, kind=kind, trace=trace, extra_payload=extra_payload)), daemon=True); th.start()
    perf("ack_start")
    say(chosen_ack, cfg, role="ack")
    while th.is_alive() and not interrupt.is_set(): th.join(0.1)
    if interrupt.is_set():
        LEDGER.cancel(rid); log.info("webhook request abandoned rid=%s", rid); return
    if res and res[0]: wait_replies(rid, cfg, listener_ack=acknowledged, kind=kind)
    else: say("Не получилось отправить запрос, сэр.", cfg)

# ================= capture after wake =================














def _handle_turn(trig, cap, text, test, skip_s):
    cfg = load_cfg()
    try:
        log.info("TRIGGER %s%s", trig, " (test)" if test else "")
        if trig == "stop_ack":
            perf("route", route="stop_ack")
            STATE.stop_ack_active = True
            ack = pick(cfg, "ack_stop"); log.info("stop ack begin: %s interrupt=%s", ack, interrupt.is_set())
            result = say(ack, cfg, role="stop_ack")
            log.info("stop ack complete: played=%s", result); return
        if trig == "proactive":
            item=text if isinstance(text,dict) else {}
            perf("route",route="proactive_"+str(item.get("kind","file")))
            try:
                if item.get("expires") is None or time.time()<item["expires"]:
                    STATE.followup_eligible=True
                    say(item.get("text",""),cfg)
            finally:
                if not test: proactive_manager().complete(item,interrupt.is_set())
            return
        if trig == "sleep_end":
            perf("route", route="sleep_end"); say(SLEEP_END_PHRASE, cfg); return
        if trig == "sleep_hint":
            perf("route", route="sleep_hint"); STATE.followup_eligible = False
            say(SLEEP.hint_phrase(sleep_state().remaining()), cfg); return
        if trig == "timer_fire":
            perf("route", route="timer_fire")
            notice = text if isinstance(text,dict) else {}
            try:
                beep()
                if notice.get("kind") == "timer": beep()
            except Exception: pass
            say(notice.get("label") or "Сэр, время вышло.", cfg); return
        ok = True
        if text is None:
            pause = float(cfg.get("wake_ack_after_s", DIALOG.DEFAULTS["wake_ack_after_s"])) if trig == "wake_word" else None
            text, conf, g = ("", 0, "") if cap is None else capture_phrase(cap, cfg, float(cfg["phrase_wait_s"]), skip_s, wake_pause_s=pause)
            FSM.to(Mode.PROCESSING, "captured")
            text, ok = choose(text, conf, g, cfg)
            if STATE.dropped: return
        else:
            text = strip_wake(_norm_phrase(text))
            if trig != "followup":
                STATE.last_input_conf = 1.0
                STATE.last_input_end = None
        if not text:
            say(pick(cfg, "ack_wake"), cfg, role="wake")
            if interrupt.is_set(): return
            cap2 = Capture(); STATE.capture = cap2; FSM.to(Mode.LISTENING, "after wake ack")
            text, conf, g = capture_phrase(cap2, cfg, float(cfg["followup_listen_s"]))
            FSM.to(Mode.PROCESSING, "captured")
            raw2 = text
            text, ok = choose(text, conf, g, cfg)
            if not text and (not g or filler_only(raw2)):
                log.info("no follow-up phrase"); return
        if interrupt.is_set(): return
        if not ok or not text:
            # Never "sorry, I did not catch that": unclear input is dropped silently.
            log.info("not understood -> silent: %r", text); return
        perf("recognized")
        confirmation = command_controller().confirmation(text,trig,STATE.last_input_conf,heard_at=STATE.last_input_end)
        al = ({"name":"shutdown_confirmation", "action":"quick2", "cmd":"shutdown_confirm", **confirmation} if confirmation is not None else match_alias(text,cfg))
        perf("route", route=(al.get("name", "local") if al else "webhook"))
        STATE.followup_eligible = not (al and al.get("action") == "stop")
        if al: run_alias(al, text, cfg, trig, test)
        else: free_phrase(text, cfg, trig, test)
    except Exception as e:
        log.exception("handle error: %s", e)
    finally:
        STATE.capture = None; STATE.stop_ack_active = False



def handle(trig, cap, text, test, skip_s, trace=None):
    """Own the entire short conversation; only silence/stop/limit returns to wake mode."""
    try:
        turns = 0
        FSM.to(Mode.LISTENING if (text is None and cap is not None) else Mode.PROCESSING, trig)
        STATE.trace = trace or SPEED.Trace(trig)
        STATE.trace.meta["test"] = bool(test)
        while True:
            STATE.reply_parts = []
            STATE.followup_eligible = False
            serial = STATE.speech_serial
            _handle_turn(trig, cap, text, test, skip_s)
            STATE.trace.finish("interrupted" if interrupt.is_set() else "done")
            cfg = load_cfg(); fs = FollowupSettings.from_cfg(cfg)
            if interrupt.is_set() or not fs.enabled: break
            if not STATE.followup_eligible or STATE.speech_serial == serial: break
            if turns >= fs.max_turns:
                log.info("follow-up turn limit -> wake mode"); break
            spoken = STATE.last_spoken
            window = fs.window_for(spoken)
            if CMDS is not None and CMDS.pending_shutdown:
                window = max(0.0,CMDS.pending_shutdown["expires"]-CMDS.clock())
            if window <= 0: break
            guard = fs.echo_guard_s
            STATE.followup_guard = True
            # Based on actual playback end, not synthesis start or webhook acknowledgement.
            delay = max(0.0, STATE.last_spoken_end + guard - time.monotonic())
            if interrupt.wait(delay): break
            log.info("follow-up open window_s=%.1f guard_s=%.2f question=%s turn=%d", window, guard, spoken.rstrip().endswith("?"), turns+1)
            STATE.trace = SPEED.Trace("followup")
            STATE.trace.meta["test"] = bool(test)
            cap = Capture(); STATE.capture = cap; STATE.followup_guard = False; FSM.to(Mode.FOLLOWUP, "window")
            text, conf, grammar = capture_phrase(cap, cfg, window, max_s=window + float(cfg["phrase_max_s"]))
            if interrupt.is_set(): break
            if text and conf < fs.min_conf:
                rescued = followup_rescue(text, grammar, cfg)
                if rescued: log.info("follow-up grammar wins: %r (free %r conf %.2f)", rescued, text, conf); text, conf = rescued, 1.0
            if not text or conf < fs.min_conf:
                STATE.trace.finish("silence")
                log.info("follow-up close: silence/low confidence text=%r conf=%.2f", text, conf); break
            if followup_echo(text, spoken):
                STATE.trace.finish("echo")
                log.info("follow-up close: likely speaker echo %r", text); break
            chosen, ok = choose(text, conf, grammar, cfg, followup=True)
            if not ok or not chosen:
                STATE.trace.finish("fragment")
                log.info("follow-up close: fragment/garbage %r", text); break
            text = chosen; cap = None; skip_s = 0.0; trig = "followup"; turns += 1; FSM.to(Mode.PROCESSING, "follow-up")
            log.info("follow-up accepted conf=%.2f text=%r", conf, text)
    except Exception:
        log.exception("conversation handler error")
    finally:
        if STATE.trace is not None: STATE.trace.finish("interrupted" if interrupt.is_set() else "done")
        STATE.trace = None
        if CMDS is not None: CMDS.clear_pending()
        STATE.capture = None; STATE.followup_guard = False
        STATE.stop_ack_active = False; FSM.to(Mode.IDLE, "conversation over"); busy.clear()

# ================= clap detector =================




PRO_MANAGER = None
def proactive_manager():
    global PRO_MANAGER
    if PRO_MANAGER is None: PRO_MANAGER = PROACTIVE.Manager(BASE)
    return PRO_MANAGER

def request_morning(job,cfg,test=False):
    extra={k:v for k,v in job.items() if k not in ("request_id","kind","date","attempts","retry_at")}
    text="Составь короткий утренний брифинг по моим свежим данным. Ответ только в указанном proactive outbox, без вводного подтверждения."
    result=False
    try: result=call_webhook(job["request_id"],text,"presence",cfg,test,listener_ack="",kind="morning_briefing",extra_payload=extra)
    finally:
        if not test: proactive_manager().morning_result(job,result,cfg)
    log.info("morning briefing POST date=%s ok=%s",job.get("local_date"),bool(result))




VERIFIER = None
def speaker_check(ring, end, cfg):
    """(ok, score) of the owner-voice check on the audio that ends at the wake word; (True, None) when off."""
    global VERIFIER
    if not cfg.get("speaker_verify_enabled"): return True, None
    if VERIFIER is None: VERIFIER = SPEAKER.SpeakerVerifier(BASE, cfg)
    VERIFIER.cfg = cfg
    win = int(float(VERIFIER.setting("speaker_window_s")) * SR)
    ok, score = VERIFIER.check(ring_audio(ring, end - win, end))
    if score is not None: log.info("speaker %s score=%.3f threshold=%.3f", "OK" if ok else "REJECTED", score, VERIFIER.threshold())
    return ok, score

def speaker_ok(ring, end, cfg):
    """Optional owner-voice check (off by default): True unless the profile rejects the voice."""
    return speaker_check(ring, end, cfg)[0]

def owner_confirmed(ring, end, cfg):
    """Stricter than speaker_ok: only True when verification is on and actually scored the owner's voice."""
    ok, score = speaker_check(ring, end, cfg)
    return bool(ok and score is not None)

def sleep_hint_due(cfg):
    """A bare «Джарвис» during sleep gets at most one spoken hint per interval."""
    if not cfg.get("sleep_hint_enabled", SLEEP.DEFAULTS["sleep_hint_enabled"]): return False
    gap = float(cfg.get("sleep_hint_interval_s", SLEEP.DEFAULTS["sleep_hint_interval_s"]))
    return time.time() - float(STATE.sleep_hint_at or 0) >= gap

def preload_speaker(cfg):
    """Load the voice profile at startup so the log shows whether owner verification is active."""
    global VERIFIER
    if not cfg.get("speaker_verify_enabled"): log.info("speaker verify off"); return
    VERIFIER = SPEAKER.SpeakerVerifier(BASE, cfg)
    if VERIFIER.ready(): log.info("speaker verify active threshold=%.3f profile_clips=%s", VERIFIER.threshold(), VERIFIER.profile.get("count"))

def main():
    cfg = load_cfg()
    LP.TIMERS = command_controller().timers
    pm=proactive_manager(); next_proactive=0.0
    ASR.quiet()
    mdir = [d for d in os.listdir(os.path.join(BASE, "models")) if d.startswith("vosk-model")]
    ready = threading.Event(); model_error = []; model_box = []
    def warm_vosk():
        t0 = time.monotonic()
        try: model_box.append(ASR.load_model(os.path.join(BASE, "models", mdir[0])))
        except Exception as e: model_error.append(e)
        finally:
            ready.set(); log.info("vosk background warmup %.3fs", time.monotonic()-t0)
    threading.Thread(target=warm_vosk, name="vosk-warmup", daemon=True).start()
    threading.Thread(target=precache, args=(cfg,), name="tts-warmup", daemon=True).start()
    OUTBOX.signal.start(cfg.get("outbox_watch_enabled", True),cfg.get("outbox_event_batch_s",0.02))
    while not ready.wait(0.1):
        if os.path.exists(STOP_FILE):
            RUNTIME.mark_stop(BASE); os.remove(STOP_FILE); OUTBOX.signal.stop(); return
    if model_error: raise model_error[0]
    STATE.model = model_box[0]
    srec = None; sbase = 0; wake_check = None
    if sleep_state().active(): log.info("sleep mode active for %.0fs more", sleep_state().remaining())
    oww = None
    if cfg["oww_enabled"]:
        try:
            from openwakeword.model import Model as OWW
            oww = OWW(wakeword_models=[os.path.join(BASE, "models", "hey_jarvis_v0.1.onnx")], inference_framework="onnx")
            log.info("openWakeWord loaded")
        except Exception as e:
            log.warning("openWakeWord unavailable: %s", e)
    clap = ClapDetector()

    def start(trig, pre=None, text=None, test=False, skip_s=0.0):
        interrupt.clear(); busy.set()
        cap = Capture(pre) if (text is None and pre is not None) else None
        STATE.capture = cap
        threading.Thread(target=handle, args=(trig, cap, text, test, skip_s, SPEED.Trace(trig)), daemon=True).start()

    dev = pick_device(sd, cfg)
    stream = MIC.open(sd, dev)
    stream.start()
    log.info("listening (v3.18.0) on device %s: %s", dev, sd.query_devices(dev)["name"] if dev is not None else sd.query_devices(kind="input")["name"])
    preload_speaker(cfg)
    pos = 0; ring = collections.deque(maxlen=int(8 * SR / CHUNK)); wrec = ASR.wake_recognizer(); wbase = 0
    last_end = 0.0; lastlvl = time.time(); lastmem = time.monotonic(); was_busy = False; barge_armed = False; pending = None
    TEST_BARGE = os.path.join(BASE, "test_bargein"); brec = None; brfree = None; free_last = (0, ""); bagc = None; last_clean = 0; bframes = 0
    def do_stop(reason):
        log.info("STOP barge-in (%s): speech stopped", reason)
        interrupt.set()  # the speech thread stops its own stream
        LEDGER.cancel(STATE.rid)
        STATE.stop_pending = True
    while True:
        try:
            if os.path.exists(STOP_FILE):
                RUNTIME.mark_stop(BASE); os.remove(STOP_FILE); log.info("stop file -> intentional exit"); interrupt.set(); PLAYER.idle(1.0); break
            if not busy.is_set() and os.path.exists(TEST_TRIGGER):
                tt = read_text(TEST_TRIGGER).strip(); os.remove(TEST_TRIGGER); cfg = load_cfg()
                log.info("test_trigger %r", tt)
                if tt.lower() in ("clap",): start("clap", text="", test=True)
                elif tt.lower() in ("", "wake", "джарвис", "хей джарвис"): start("wake_word", text="", test=True)
                else: start("wake_word", text=tt, test=True)
            sleeping = sleep_state().active()
            if not busy.is_set() and not was_busy: FSM.to(Mode.SLEEP if sleeping else Mode.IDLE, "sleep" if sleeping else "awake")
            if not busy.is_set() and not was_busy and sleep_state().poll(WAKE_FILE):
                srec = None; start("sleep_end", text=""); continue
            if time.monotonic()>=next_proactive:
                next_proactive=time.monotonic()+max(1,float(cfg.get("proactive_tick_s",5)))
                job=pm.tick(cfg)
                if job: threading.Thread(target=request_morning,args=(job,dict(cfg)),name="morning-post",daemon=True).start()
                if not sleeping and not busy.is_set() and not was_busy and pending is None and not STATE.stop_pending:
                    item=pm.take(cfg)
                    if item: start("proactive",text=item)
            if not sleeping and not busy.is_set() and not was_busy and pending is None and not STATE.stop_pending and pm.can_speak(cfg):
                for notice in LP.TIMERS.pop_fired(limit=1): start("timer_fire", text=notice, test=False); break
            if time.time() - lastlvl > cfg["level_log_interval_s"]:
                MIC.levels.report(); lastlvl = time.time()
            if time.monotonic() - lastmem > float(cfg.get("memory_log_interval_s", 1800)):
                lastmem = time.monotonic()
                if not busy.is_set() and RUNTIME.idle_for(STATE.last_spoken_end or 0.0, lastmem) > float(cfg.get("memory_trim_idle_s", 900)):
                    trim_memory()  # pages come back on demand; frees RAM for calls between uses
                m = mem_info()
                log.info("memory: ws=%dMB priv=%dMB peak_ws=%dMB threads=%d", m["ws"], m["priv"], m["peak_ws"], threading.active_count())
                if not busy.is_set() and RUNTIME.memory_over_limit(m["priv"], cfg.get("memory_restart_mb", 0)):
                    log.warning("memory guard: priv=%dMB > %sMB while idle -> restart via supervisor", m["priv"], cfg.get("memory_restart_mb"))
                    STATE.exit_code = RUNTIME.MEMORY_RESTART_CODE; break
            try: x = MIC.queue.get(timeout=0.3)
            except queue.Empty: continue
            st = pos; pos += len(x); ring.append((st, x))
            MIC.levels.add(x)
            i16 = (np.clip(x, -1, 1) * 32767).astype(np.int16)
            cap = STATE.capture
            if cap is not None: cap.q.put(x)
            sc = max(oww.predict(i16).values()) if oww is not None else 0.0
            if time.time() - last_clean > 2:
                last_clean = time.time()
                OUTBOX.purge_cancelled(LEDGER)
            if busy.is_set():
                if not was_busy:
                    brec = ASR.stop_recognizer(cfg); bagc = AGC(cfg)
                    brfree = ASR.recognizer(); free_last = (0, ""); bframes=0
                was_busy = True
                if cap is None and not interrupt.is_set() and not STATE.stop_ack_active and not STATE.followup_guard:
                    if os.path.exists(TEST_BARGE):
                        tb = read_text(TEST_BARGE).strip(); os.remove(TEST_BARGE); log.info("test_bargein %r (speaking=%s)", tb, speaking.is_set())
                        do_stop("test: " + tb); continue
                    try:
                        bb = (bagc(x) * 32767).astype(np.int16).tobytes()
                        borigin=st-bframes; bframes+=len(x)
                        if brfree.AcceptWaveform(bb):
                            fr = json.loads(brfree.Result())
                            fw = fr.get("result", [])
                            fc = sum(w.get("conf",0) for w in fw) / max(1,len(fw))
                            free_last = (time.monotonic(), fr.get("text", "") if fc >= 0.5 else "")
                            if PROACTIVE.priority_candidate(fr.get("text",""),fc,STATE.speaking_text,cfg) and any(w.get("word") in PRIORITY_WAKE_WORDS and w.get("conf",0)>=float(cfg.get("priority_wake_min_conf",.85)) for w in fw[:3]):
                                log.info("PRIORITY vosk wake conf=%.2f -> interrupt and capture",fc)
                                interrupt.set()
                                LEDGER.cancel(STATE.rid)
                                wake=next((w for w in fw[:3] if w.get("word") in PRIORITY_WAKE_WORDS),None)
                                pending=borigin+int((wake.get("start",0) if wake else 0)*SR)-int(.25*SR)
                                continue
                        if brec.AcceptWaveform(bb):
                            ws = json.loads(brec.Result()).get("result", [])
                            if ws:
                                conf = sum(w.get("conf", 0) for w in ws) / len(ws); ph = " ".join(w["word"] for w in ws)
                                echo = any(w["word"].replace("ё", "е") in STATE.speaking_text for w in ws)
                                partial_free = json.loads(brfree.PartialResult()).get("partial", "")
                                recent_free = free_last[1] if time.monotonic() - free_last[0] < 1.2 else ""
                                corroborated = corroborated_stop(ph, partial_free) or corroborated_stop(ph, recent_free)
                                ok = stop_candidate(ph, conf, echo, cfg) and corroborated
                                log.info("barge-in candidate %r conf=%.2f echo=%s speaking=%s free=%r corroborated=%s -> %s", ph, conf, echo, speaking.is_set(), partial_free or recent_free, corroborated, "STOP" if ok else "ignored")
                                if ok: do_stop(ph); continue
                    except Exception as e: log.info("barge recognizer error: %s", e)
                if cap is None and oww is not None and not STATE.stop_ack_active and not STATE.followup_guard:
                    if sc < 0.2: barge_armed = True
                    elif barge_armed and sc >= cfg["barge_in_threshold"] and not interrupt.is_set():
                        log.info("BARGE-IN oww %.2f -> interrupt", sc); interrupt.set()
                        LEDGER.cancel(STATE.rid)
                        pending = st + len(x) - int(cfg["wake_prebuffer_s"] * SR)
                continue
            if was_busy:
                was_busy = False; last_end = time.time(); wrec = ASR.wake_recognizer(); wbase = pos; wake_check = None; clap.events = []; clap.cur = None
                if oww is not None: oww.reset()
                cfg = load_cfg(); STATE.rid = None
                if STATE.stop_pending:
                    STATE.stop_pending = False; pending = None; start("stop_ack", text=""); continue
                if pending is not None:
                    pre = frames_after(ring, pending); pending = None; barge_armed = False
                    start("wake_word", pre=pre, skip_s=0.0); continue
            if sleeping:
                # Sleep: no clap, no wake word, no follow-ups. Only a strict «Джарвис, проснись».
                wake_check = None
                if srec is None: srec = ASR.sleep_recognizer(); sbase = st
                if srec.AcceptWaveform(i16.tobytes()):
                    ws = json.loads(srec.Result()).get("result", [])
                    said = " ".join(w.get("word", "") for w in ws)
                    if SLEEP.is_wake_phrase(said) and min(w.get("conf", 0) for w in ws) >= 0.9:
                        a = sbase + int((ws[0]["start"] - 0.45) * SR); b = sbase + int((ws[-1]["end"] + 0.3) * SR)
                        if verify_wake(ring, a, b, cfg, need=("проснись",), min_conf=GATE.setting(cfg, "sleep_wake_min_conf")):
                            sleep_state().stop("phrase"); srec = None
                            start("sleep_end", text=""); continue
                    elif said == SLEEP.HINT_WORD and ws and ws[0].get("conf", 0) >= 0.9 and sleep_hint_due(cfg):
                        a = sbase + int((ws[0]["start"] - 0.45) * SR); b = sbase + int((ws[-1]["end"] + 0.3) * SR)
                        if verify_wake(ring, a, b, cfg, min_conf=GATE.setting(cfg, "sleep_wake_min_conf")) and owner_confirmed(ring, b, cfg):
                            STATE.sleep_hint_at = time.time(); start("sleep_hint", text=""); continue
                continue
            srec = None
            trig = None; frm = None; skip = 0.0
            if cfg["clap_enabled"] and clap.feed(x, st, cfg): trig = "clap"
            if cfg["wake_word_enabled"] and not trig:
                if sc >= cfg["oww_threshold"] and wake_check is None:
                    log.info("oww score %.2f", sc)
                    frm = st + len(x) - int(cfg["wake_prebuffer_s"] * SR)
                    if sc >= float(GATE.setting(cfg, "oww_strong_threshold")):
                        if speaker_ok(ring, pos, cfg): trig = "wake_word"
                    else: wake_check = {"a": frm, "b": pos + int(0.3 * SR), "frm": frm, "src": "oww"}
                if wrec.AcceptWaveform(i16.tobytes()):
                    res = json.loads(wrec.Result())
                    ws = [w for w in res.get("result", []) if w.get("word") == "джарвис"]
                    if ws and ws[0].get("conf", 0) >= cfg["vosk_wake_min_conf"]:
                        if not trig and (wake_check is None or wake_check["src"] == "oww"):
                            log.info("vosk wake candidate conf %.2f", ws[0]["conf"])
                            wake_check = {"a": wbase + int((ws[0]["start"] - float(GATE.setting(cfg, "wake_verify_pre_s"))) * SR),
                                          "b": wbase + int((ws[-1]["end"] + float(GATE.setting(cfg, "wake_verify_post_s"))) * SR),
                                          "frm": wbase + int(ws[-1]["end"] * SR) - int(VOSK_WAKE_TAIL_S * SR), "src": "vosk"}
                    elif ws: log.info("vosk wake rejected conf %.2f", ws[0].get("conf", 0))
                if not trig and wake_check is not None and pos >= wake_check["b"]:
                    wc, wake_check = wake_check, None
                    if verify_wake(ring, wc["a"], wc["b"], cfg) and speaker_ok(ring, wc["b"], cfg):
                        trig = "wake_word"; frm = wc["frm"]; skip = VOSK_WAKE_SKIP_S if wc["src"] == "vosk" else 0.0
            if trig and time.time() - last_end > cfg["cooldown_s"]:
                barge_armed = False
                if trig == "clap": start("clap", text="")
                else:
                    pre = frames_after(ring, frm)
                    start("wake_word", pre=pre, skip_s=skip)
        except Exception as e:
            log.exception("main loop error: %s", e); time.sleep(0.5)
    OUTBOX.signal.stop()

if __name__ == "__main__":
    guard=RUNTIME.Singleton(BASE,"listener")
    if not guard.acquire():
        log.info("listener already running; duplicate start ignored"); raise SystemExit(0)
    try: main()
    except Exception as e:
        log.exception("fatal: %s", e); raise
    finally: guard.close()
    if STATE.exit_code: raise SystemExit(STATE.exit_code)
