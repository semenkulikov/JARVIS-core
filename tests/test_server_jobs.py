"""Server requests outside the conversation: background worker, reply turns, stop vs. other barge-ins."""
import threading
import time

import pytest

from jarvis.app import server_jobs as JOBS
from jarvis.core.state import ServerJob


class Sig:
    def clear(self): pass
    def wait(self, cfg): time.sleep(0.01)


class SlowServer:
    """Accepts the POST after ``delay`` seconds; the test writes the reply files itself."""

    def __init__(self, delay=0.0, ok=True):
        self.delay, self.ok, self.calls = delay, ok, []

    def call(self, rid, text, trigger, cfg, test, listener_ack="", kind="free", trace=None, extra_payload=None):
        self.calls.append((rid, text, kind)); time.sleep(self.delay); return self.ok


@pytest.fixture
def env(app, cfg, monkeypatch, tmp_path):
    from jarvis.adapters.outbox import Outbox
    box = tmp_path / "outbox"
    outbox = Outbox(str(box), done=str(box / "done"), signal=Sig()); outbox.ensure()
    server = SlowServer(delay=0.3)
    monkeypatch.setattr(app.c, "outbox", outbox)
    monkeypatch.setattr(app.c.jobs, "outbox", outbox)
    monkeypatch.setattr(app.c.jobs, "transport", server)
    said = []
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: said.append(t) or True)
    cancelled = []
    real_cancel = app.c.ledger.cancel
    monkeypatch.setattr(app.c.ledger, "cancel", lambda rid: (cancelled.append(rid), real_cancel(rid)))
    cfg.update(reply_timeout_s=5.0, server_notice_s=60.0, server_down_wait_s=0.3, server_reply_gap_s=0.05)
    return box, server, said, cancelled


def wait_for(cond, timeout=3.0):
    t = time.time()
    while time.time() - t < timeout:
        if cond(): return True
        time.sleep(0.01)
    return False


def ask(app, text="какая погода"):
    app.conversation.handle("wake_word", None, text, False, 0.0)
    return app.c.jobs.pending()[-1]


def test_ask_only_queues_and_acknowledges(app, cfg, env):
    box, server, said, _ = env
    job = ask(app)
    assert said and not app.c.signals.busy.is_set() and job.text == "какая погода" and job.trace is not None
    assert wait_for(lambda: server.calls) and server.calls[0][0] == job.rid


def test_local_command_while_the_server_thinks_does_not_cancel(app, cfg, env, monkeypatch):
    box, server, said, cancelled = env
    keys = []
    monkeypatch.setattr(app.c.laptop, "press", lambda vk, n=1: keys.append(vk))
    job = ask(app)
    said.clear()
    app.conversation.handle("wake_word", None, "громче", False, 0.0)  # runs at once, mid-request
    assert keys and not job.cancelled and cancelled == []
    (box / f"{job.rid}.1.txt").write_text("Первая часть ответа.", encoding="utf-8")
    (box / f"{job.rid}.txt").write_text("Вторая часть.", encoding="utf-8")
    assert wait_for(lambda: job.finished)
    said.clear()
    app.conversation.handle("server_reply", None, app.c.jobs.ready(), False, 0.0)
    assert said == ["Первая часть ответа.", "Вторая часть."] and job.done and cancelled == []
    assert app.c.state.last_reply == "Первая часть ответа. Вторая часть."


def test_stop_during_the_reply_cancels_only_that_job_and_its_files(app, cfg, env, monkeypatch):
    box, server, said, cancelled = env
    job = ask(app)
    (box / f"{job.rid}.1.txt").write_text("Длинный ответ.", encoding="utf-8")
    assert wait_for(lambda: job.has_parts(time.time()))

    def say(text, c, **k):
        app.listener.do_stop("стоп")          # the barge-in recognizer heard «стоп» mid-sentence
        (box / f"{job.rid}.2.txt").write_text("Остаток.", encoding="utf-8")  # the server keeps writing
        return False
    monkeypatch.setattr(app.conversation, "say", say)
    app.conversation.handle("server_reply", None, job, False, 0.0)
    assert job.cancelled and cancelled == [job.rid] and app.c.state.stop_pending
    app.c.outbox.purge_cancelled(app.c.ledger)  # the listener's periodic clean-up
    assert not [p for p in box.iterdir() if p.name.startswith(job.rid)]


def test_other_barge_in_pauses_the_reply_and_it_resumes(app, cfg, env, monkeypatch):
    box, server, said, cancelled = env
    job = ask(app)
    (box / f"{job.rid}.txt").write_text("Ответ целиком.", encoding="utf-8")
    assert wait_for(lambda: job.finished)
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: app.c.signals.interrupt.set() or False)
    app.conversation.speak_job(job, cfg)
    assert not job.cancelled and app.c.jobs.ready() is job and cancelled == []
    app.c.signals.interrupt.clear(); said.clear()
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: said.append(t) or True)
    app.conversation.speak_job(job, cfg)
    assert said == ["Ответ целиком."] and job.done


def test_stop_command_after_a_priority_wake_cancels_the_paused_reply(app, cfg, env, monkeypatch):
    box, server, said, cancelled = env
    job = ask(app)
    (box / f"{job.rid}.txt").write_text("Ответ.", encoding="utf-8")
    assert wait_for(lambda: job.finished)
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: app.c.signals.interrupt.set() or False)
    app.conversation.speak_job(job, cfg)
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: True)
    app.c.signals.interrupt.clear()
    app.conversation.handle("wake_word", None, "стоп", False, 0.0)
    assert job.cancelled and cancelled == [job.rid]


def test_server_down_notice_and_local_commands_still_work(app, cfg, env):
    box, server, said, cancelled = env
    app.c.ledger.down_since = time.time()
    job = ask(app)
    assert wait_for(lambda: job.finished, 3.0)
    part = job.pop(time.time())
    assert part.text == JOBS.SERVER_DOWN_PHRASE and not part.data
    said.clear(); app.conversation.handle("wake_word", None, "который час", False, 0.0)
    assert said and said[0].startswith("Сейчас")


def test_third_request_is_refused_and_replies_never_mix(app, cfg, env):
    box, server, said, cancelled = env
    server.delay = 0.0
    first, second = ask(app, "первый вопрос"), ask(app, "второй вопрос")
    said.clear()
    app.conversation.handle("wake_word", None, "третий вопрос", False, 0.0)
    assert said == [JOBS.BUSY_PHRASE] and len(app.c.jobs.pending()) == 2
    (box / f"{second.rid}.txt").write_text("Ответ на второй.", encoding="utf-8")
    assert wait_for(lambda: server.calls and len(server.calls) >= 1)
    assert app.c.jobs.ready() is None  # the second answers first, but waits for the first
    (box / f"{first.rid}.txt").write_text("Ответ на первый.", encoding="utf-8")
    assert wait_for(lambda: app.c.jobs.ready() is first)
    app.conversation.speak_job(first, cfg)
    assert wait_for(lambda: app.c.jobs.ready() is second)
    app.conversation.speak_job(second, cfg)
    assert said[-2:] == ["Ответ на первый.", "Ответ на второй."]


def test_repeat_reads_the_last_spoken_server_answer(app, cfg, env, monkeypatch):
    box, server, said, cancelled = env
    job = ask(app)
    (box / f"{job.rid}.1.txt").write_text("Часть один.", encoding="utf-8")
    (box / f"{job.rid}.txt").write_text("Часть два.", encoding="utf-8")
    assert wait_for(lambda: job.finished)
    app.conversation.speak_job(job, cfg)
    said.clear()
    app.conversation.handle("wake_word", None, "повтори", False, 0.0)
    assert said == ["Часть один. Часть два."]


def test_unheard_parts_expire():
    job = ServerJob(rid="r", text="t", kind="free", created=0.0)
    job.push("старое", expires=10.0); job.push("свежее", expires=100.0)
    assert job.pop(50.0).text == "свежее" and job.pop(50.0) is None


def test_listener_starts_a_reply_turn_only_when_idle(app, cfg, monkeypatch):
    from jarvis.adapters.audio import ClapDetector
    from jarvis.app import listener as L
    started = []
    monkeypatch.setattr(app.listener, "start", lambda trig, **kw: started.append((trig, kw.get("text"))))
    pm = type("PM", (), {"tick": lambda self, c: None, "take": lambda self, c: None, "can_speak": lambda self, c: False})()
    lp = L.Loop(cfg=cfg, pm=pm, oww=None, clap=ClapDetector()); lp.next_proactive = float("inf")
    job = ServerJob(rid="r", text="t", kind="free", created=time.time())
    monkeypatch.setattr(app.c.jobs, "ready", lambda: job)
    app.c.signals.busy.set()
    app.listener._housekeeping(lp); assert started == []
    app.c.signals.busy.clear()
    app.listener._housekeeping(lp); assert started == [("server_reply", job)]


def test_worker_posts_in_the_background(app, cfg, env):
    box, server, said, cancelled = env
    server.delay = 0.5
    t = time.time(); ask(app)
    assert time.time() - t < 0.4 and threading.active_count() >= 2
