"""Seams of the composition root, the conversation and the microphone loop (no audio, no models)."""
import logging
import os
import runpy

import numpy as np
import pytest

from jarvis.adapters import paths as jarvis_paths
from jarvis.adapters import runtime as RUNTIME
from jarvis.adapters.audio import CHUNK, ClapDetector
from jarvis.app import listener as L
from jarvis.app import main as MAIN
from jarvis.core.state import Mode


def test_one_state_shared_by_every_component(app):
    c = app.c
    assert c.voice.state is c.state and c.asr.state is c.state and c.router.state is c.state
    assert c.transport.signals is c.signals and c.voice.signals is c.signals
    assert app.conversation.c is c and app.listener.conversation is app.conversation
    assert os.path.isdir(c.paths.cache) and os.path.isdir(c.paths.at("outbox"))


def test_lazy_services_are_created_on_first_use(app):
    c = app.c
    assert c.controller.peek() is None and c.sleep.peek() is None and c.proactive.peek() is None
    assert c.router.shutdown_pending() is False
    assert app.conversation.controller() is c.controller.peek() is c.controller.get()
    assert app.conversation.sleep().active() is False


def test_two_apps_do_not_share_state(tmp_path):
    from jarvis.app.context import build_app
    import sounddevice as sd
    a, b = build_app(tmp_path / "a", sd=sd), build_app(tmp_path / "b", sd=sd)
    a.c.state.last_reply = "x"; a.c.signals.busy.set()
    assert b.c.state.last_reply == "" and not b.c.signals.busy.is_set() and a.c.jobs is not b.c.jobs


def test_timer_turn_beeps_and_speaks_label(app, cfg, monkeypatch):
    said, beeps = [], []
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: said.append(t) or True)
    monkeypatch.setattr(app.c.voice, "beep", lambda: beeps.append(1))
    app.conversation.handle_turn("timer_fire", None, {"kind": "timer", "label": "Чай готов, сэр."}, False, 0.0)
    assert said == ["Чай готов, сэр."] and len(beeps) == 2


def test_conversation_ends_idle_and_not_busy(app, cfg, monkeypatch):
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: True)
    app.c.signals.busy.set()
    app.conversation.handle("wake_word", None, "который час", True, 0.0)
    assert app.c.fsm.mode is Mode.IDLE and not app.c.signals.busy.is_set() and app.c.state.trace is None


@pytest.fixture
def loop(app, cfg, monkeypatch):
    started = []
    monkeypatch.setattr(app.listener, "start", lambda trig, **kw: started.append((trig, kw)))
    pm = type("PM", (), {"tick": lambda self, c: None, "take": lambda self, c: None, "can_speak": lambda self, c: False})()
    lp = L.Loop(cfg=cfg, pm=pm, oww=None, clap=ClapDetector())
    lp.next_proactive = float("inf")
    return lp, started


def test_stop_file_ends_the_loop(app, loop, monkeypatch):
    lp, _ = loop
    marked = []
    monkeypatch.setattr(RUNTIME, "mark_stop", lambda home: marked.append(home))
    open(app.c.paths.stop_file, "w").close()
    assert app.listener.step(lp) == L.STOP
    assert marked == [app.c.paths.home] and not os.path.exists(app.c.paths.stop_file) and app.c.signals.interrupt.is_set()


def test_test_trigger_starts_a_test_turn(app, loop):
    lp, started = loop
    with open(app.c.paths.test_trigger, "w", encoding="utf-8") as f: f.write("который час")
    assert app.listener._housekeeping(lp) is None
    assert started == [("wake_word", {"text": "который час", "test": True})]


def test_stop_after_speech_plays_the_stop_ack(app, loop, monkeypatch):
    lp, started = loop
    monkeypatch.setattr(app.c.asr, "wake_recognizer", lambda cfg=None: "wake-rec")
    lp.was_busy = True; app.c.state.stop_pending = True; lp.pending = 123
    assert app.listener._after_busy(lp) is True
    assert started == [("stop_ack", {"text": ""})] and lp.pending is None and lp.wrec == "wake-rec" and not app.c.state.stop_pending


def test_clap_starts_a_turn_after_cooldown(app, loop, monkeypatch):
    lp, started = loop
    monkeypatch.setattr(lp.clap, "feed", lambda x, pos, c: True)
    lp.cfg = dict(lp.cfg, clap_enabled=True, wake_word_enabled=False, cooldown_s=0)
    x = np.zeros(CHUNK, np.float32)
    app.listener._detect_wake(lp, x, 0, x.astype(np.int16), 0.0)
    assert started == [("clap", {"text": ""})]


def test_main_ignores_a_second_listener(tmp_path, monkeypatch):
    class Held:
        def __init__(self, base, role): pass
        def acquire(self): return False
        def close(self): pytest.fail("not acquired")
    monkeypatch.setattr(jarvis_paths, "HOME", tmp_path)
    monkeypatch.setattr(jarvis_paths, "log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(RUNTIME, "Singleton", Held)
    log = logging.getLogger("jarvis"); before = list(log.handlers)
    try:
        assert MAIN.run() == 0
    finally:
        for h in log.handlers[len(before):]: h.close(); log.removeHandler(h)
    assert "duplicate start ignored" in (tmp_path / "logs" / MAIN.LOG_FILE).read_text(encoding="utf-8")


def test_entry_script_is_a_thin_shim(monkeypatch):
    for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"): monkeypatch.delenv(k, raising=False)
    ns = runpy.run_path(os.path.join(os.path.dirname(MAIN.__file__), "..", "..", "jarvis_voice.py"), run_name="not_main")
    assert ns["run"] is MAIN.run and os.environ["OMP_NUM_THREADS"] == "2"


def test_listener_runs_until_the_stop_file(app, cfg, monkeypatch, caplog):
    """Whole startup path with fakes: model warmup, device, 'listening' line, frames, intentional exit."""
    import threading
    import time
    c = app.c
    os.makedirs(os.path.join(c.paths.models, "vosk-model-small-ru"))
    cfg.update(oww_enabled=False, clap_enabled=False, wake_word_enabled=False, mic_name_contains=["none"])
    class Rec:
        def AcceptWaveform(self, b): return False
    class Stream:
        def start(self): pass
    class Signal:
        def start(self, *a): pass
        def stop(self): pass
    monkeypatch.setattr(c.asr, "quiet", lambda: None)
    monkeypatch.setattr(c.asr, "load_model", lambda path: "model:" + os.path.basename(path))
    monkeypatch.setattr(c.asr, "wake_recognizer", lambda cfg=None: Rec())
    monkeypatch.setattr(c.mic, "open", lambda sd, dev: Stream())
    monkeypatch.setattr(c.speaker, "preload", lambda cfg: None)
    monkeypatch.setattr(c.outbox, "signal", Signal())
    monkeypatch.setattr(c.player, "idle", lambda t: True)
    monkeypatch.setattr(app.warmup, "run", lambda cfg: None)
    monkeypatch.setattr(RUNTIME, "mark_stop", lambda home: None)
    sd = app.listener.sd
    monkeypatch.setattr(sd, "query_devices", lambda *a, **k: [] if not a and not k else {"name": "Fake mic"}, raising=False)
    monkeypatch.setattr(sd, "query_hostapis", lambda: [], raising=False)
    for _ in range(3): c.mic.queue.put(np.zeros(CHUNK, np.float32))
    def stop_soon():
        while not c.mic.queue.empty(): time.sleep(0.01)
        open(c.paths.stop_file, "w").close()
    threading.Thread(target=stop_soon, daemon=True).start()
    from jarvis import __version__
    with caplog.at_level("INFO", logger="jarvis"):
        app.listener.run()
    assert c.state.model == "model:vosk-model-small-ru" and c.mic.queue.empty()
    assert f"listening (v{__version__}) on device None: Fake mic" in caplog.text and "stop file -> intentional exit" in caplog.text
    assert "main loop error" not in caplog.text


def test_adapters_are_seen_through_the_ports(app):
    from jarvis.app.context import ports_of
    speech, synth, asr, transport, status = ports_of(app.c)
    assert speech.say is not None and synth.get_audio and asr.capture and transport.call and status.cached_status
