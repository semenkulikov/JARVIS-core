"""Protocols on fake services only: no window is opened, closed or locked, nothing is played."""
import copy
import os
import time

import pytest

from command_fakes import FakeServices, run
from jarvis.app.context import build_controller
from jarvis.commands import protocols as CMD
from jarvis.commands.base import CommandContext
from jarvis.core import protocols as P
from jarvis.core import routing as ROUTING
from jarvis.core import sleep as SLEEP


class Journal(list):
    def rec(self, *call): self.append(call)


class Backend:
    """Records every desktop action in the shared journal; ``fail`` names the actions that raise."""

    is_fake = True

    def __init__(self, journal, fail=()):
        self.j = journal; self.fail = set(fail); self.pid = 100

    def _do(self, name, *args):
        self.j.rec(name, *args)
        if name in self.fail: raise OSError(name + "_failed")

    def media(self, play=False): self._do("media", play)
    def mute(self, muted): self._do("mute", muted)
    def volume(self, v): self._do("volume", v)
    def output_volume(self): return 40.0
    def lock(self): self._do("lock")
    def shutdown(self, secs): self._do("shutdown", secs)
    def launch(self, target): self._do("launch", target)
    def close_apps(self, names, protect): self._do("close_apps", tuple(names), frozenset(protect)); return len(names)
    def close_windows(self, protect): self._do("close_windows", frozenset(protect)); return 7
    def minimize_all(self): self._do("minimize_all")
    def screen_size(self): return (1920, 1080)
    def open_console(self, cmd, title, rect, cwd=None): self._do("open_console", cmd, rect); self.pid += 1; return self.pid
    def end_process(self, pid): self._do("end_process", pid)


class Sleep:
    def __init__(self, journal): self.j = journal; self.until = None; self.quiet_end = False
    def start(self, secs, quiet_end=False): self.j.rec("sleep", round(secs), quiet_end); self.until = time.time() + secs; self.quiet_end = quiet_end
    def stop(self, reason): self.j.rec("sleep_stop", reason); self.until = None; return True
    def active(self): return self.until is not None


class Proactive:
    def __init__(self, journal, alarm_in=8 * 3600): self.j = journal; self.alarm_in = alarm_in
    def next_at(self, cfg, entry): self.j.rec("next_at", entry); return None if self.alarm_in is None else time.time() + self.alarm_in
    def cancel_repeats(self, cfg, entry=None): self.j.rec("cancel_repeats", entry); return 1
    def set_dnd(self, on): self.j.rec("dnd", on)


@pytest.fixture
def rig(tmp_path):
    def make(fail=(), alarm_in=8 * 3600, clock=None):
        j = Journal(); b = Backend(j, fail)
        ctl = build_controller(tmp_path / "home", backend=b, **({"clock": clock} if clock else {}))
        s = FakeServices(controller=ctl, sleep=Sleep(j), proactive=Proactive(j, alarm_in))
        return j, s, ctl
    return make


def names(journal): return [c[0] for c in journal]


def route(text, cfg): return ROUTING.match_alias(text, cfg)


# ------------------------------------------------------------ config and phrases
def test_default_protocols():
    ps = {p.name: p for p in P.parse(P.DEFAULTS)}
    assert list(ps) == ["Спящая красавица", "Негры пашут", "Бобик сдох", "Взлом Пентагона"]
    assert ps["Бобик сдох"].needs_confirm and not ps["Взлом Пентагона"].needs_confirm
    assert all(s.name in CMD.STEPS for p in ps.values() for s in p.steps)


def test_shutdown_step_always_asks_and_bad_entries_are_skipped(caplog):
    ps = P.parse({"protocols": [{"name": "Конец", "phrases": ["протокол конец"], "steps": [{"step": "shutdown", "seconds": 120}]},
                                {"name": "Пусто", "phrases": ["протокол пусто"], "steps": []}, {"name": "", "phrases": ["x"], "steps": ["lock"]}]})
    assert [p.name for p in ps] == ["Конец"] and ps[0].needs_confirm and ps[0].steps[0].params == {"seconds": 120}
    assert "'Пусто' skipped: bad steps" in caplog.text


@pytest.mark.parametrize("text,name,secs", [
    ("протокол спящая красавица", "Спящая красавица", None),
    ("протокол спящая царевна", "Спящая красавица", None),
    ("протокол спящая красавица на шесть часов", "Спящая красавица", 6 * 3600),
    ("протокол спящая красавица на сорок минут", "Спящая красавица", 40 * 60),
    ("протокол спящая красавица на двадцать часов", "Спящая красавица", SLEEP.MAX_S),
    ("протокол негры пашут", "Негры пашут", None),
    ("протокол бобик сдох", "Бобик сдох", None),
    ("протокол взлом пентагона", "Взлом Пентагона", None),
    ("протокола взлом пентагона", "Взлом Пентагона", None),
])
def test_protocol_phrases_route(cfg, text, name, secs):
    al = route(text, cfg)
    assert al["action"] == "protocol" and al["protocol"] == name and al["seconds"] == secs


@pytest.mark.parametrize("text", ["протокол спящая красавица завтра", "спящая красавица", "протокол", "протокол бобик"])
def test_not_a_protocol(cfg, text):
    al = route(text, cfg)
    assert al is None or al.get("action") != "protocol"


def test_list_and_cancel_route(cfg):
    assert route("какие протоколы", cfg)["action"] == "protocol_list"
    assert route("отмена протокола", cfg)["action"] == "protocol_cancel"
    assert route("стоп", cfg)["action"] == "stop"


def test_protocol_phrases_go_to_the_grammar_and_vocabulary(cfg):
    assert "протокол бобик сдох" in ROUTING.grammar_phrases(cfg)
    assert {"протокол спящая царевна", "какие протоколы", "отмена протокола"} <= set(P.phrases(cfg))


def test_grid_tiles_the_screen():
    assert P.grid(6, 1920, 1080) == [(0, 0, 640, 540), (640, 0, 640, 540), (1280, 0, 640, 540),
                                     (0, 540, 640, 540), (640, 540, 640, 540), (1280, 540, 640, 540)]
    assert P.grid(0, 1920, 1080) == [] and len(P.grid(4, 1920, 1080)) == 4


# ------------------------------------------------------------ every default entry, in order, on fakes
def alias(cfg, text): return route(text, cfg)


def test_sleeping_beauty_steps_in_order(cfg, rig):
    j, s, _ = rig()
    run(alias(cfg, "протокол спящая царевна"), "протокол спящая царевна", cfg, s)
    assert names(j) == ["media", "next_at", "sleep", "cancel_repeats"]
    assert j[2] == ("sleep", 8 * 3600, True)  # until the alarm, which ends sleep silently
    assert s.said == ["Спокойной ночи, сэр."] and s.state.followup_eligible is False


def test_sleeping_beauty_for_a_duration(cfg, rig):
    j, s, _ = rig()
    run(alias(cfg, "протокол спящая красавица на шесть часов"), "", cfg, s)
    assert ("sleep", 6 * 3600, False) in j and "next_at" not in names(j)


def test_sleeping_beauty_without_an_alarm_sleeps_the_default(cfg, rig):
    j, s, _ = rig(alarm_in=None)
    run(alias(cfg, "протокол спящая красавица"), "", cfg, s)
    assert ("sleep", SLEEP.DEFAULT_S, False) in j


def test_workers_protocol_launches_the_workspace_and_focus(cfg, rig):
    j, s, ctl = rig(); cfg["workspace"] = ["C:/Code/app", "https://example.invalid", "wt.exe"]
    run(alias(cfg, "протокол негры пашут"), "", cfg, s)
    assert j == [("launch", "C:/Code/app"), ("launch", "https://example.invalid"), ("launch", "wt.exe"), ("media", False)]
    assert any(t["group"] == "focus" for t in ctl.timers.items) and s.said == ["Рабочий режим включён, сэр."]


def test_bobik_asks_first_and_does_nothing_without_yes(cfg, rig):
    clock = [100.0]; j, s, ctl = rig(clock=lambda: clock[0])
    run(alias(cfg, "протокол бобик сдох"), "", cfg, s)
    assert j == [] and "Подтверждаете" in s.said[-1] and ctl.pending["kind"] == "protocol"
    answer = ctl.confirmation("нет", "followup", 1.0)
    run({"name": "protocol_confirmation", "action": "protocol_confirm", **answer}, "нет", cfg, s)
    assert j == [] and s.said[-1] == CMD.NOT_CONFIRMED


def test_bobik_runs_after_a_spoken_yes(cfg, rig):
    clock = [100.0]; j, s, ctl = rig(clock=lambda: clock[0])
    run(alias(cfg, "протокол бобик сдох"), "", cfg, s)
    clock[0] += 3; answer = ctl.confirmation("да", "followup", 0.95)
    assert answer["approved"] and answer["protocol"] == "Бобик сдох"
    run({"name": "protocol_confirmation", "action": "protocol_confirm", **answer}, "да", cfg, s)
    assert names(j) == ["close_windows", "minimize_all", "media", "lock"]  # every window, not a list
    assert os.getpid() in j[0][1]  # Jarvis protects itself
    assert s.said[-1] == "Бобик сдох, сэр."


def test_bobik_yes_too_late_or_not_a_follow_up_is_refused(cfg, rig):
    clock = [100.0]; j, s, ctl = rig(clock=lambda: clock[0])
    run(alias(cfg, "протокол бобик сдох"), "", cfg, s)
    clock[0] += 60; answer = ctl.confirmation("да", "followup", 1.0)
    run({"name": "protocol_confirmation", "action": "protocol_confirm", **answer}, "да", cfg, s)
    assert j == [] and s.said[-1] == CMD.NOT_CONFIRMED


def test_pentagon_opens_whitelisted_windows_and_cancel_closes_them(cfg, rig):
    j, s, ctl = rig()
    run(alias(cfg, "протокол взлом пентагона"), "", cfg, s)
    opened = [c for c in j if c[0] == "open_console"]
    assert [c[1] for c in opened] == list(CMD.HACKER_COMMANDS) and len(ctl.protocol_pids) == 6
    assert {c[2] for c in opened} == set(P.grid(6, 1920, 1080)) and s.said == ["Доступ получен, сэр."]
    j.clear(); run(alias(cfg, "отмена протокола"), "", cfg, s)
    assert [c for c in j if c[0] == "end_process"] == [("end_process", pid) for pid in range(101, 107)]
    assert ("dnd", False) in j and ("mute", False) in j and ("sleep_stop", "protocol_cancel") in j
    assert ctl.protocol_pids == [] and s.said[-1] == CMD.CANCELLED


def test_pentagon_commands_come_only_from_the_code(cfg, rig):
    j, s, _ = rig()
    cfg["protocols"] = [{"name": "Взлом", "phrases": ["протокол взлом"], "steps": [{"step": "hacker_windows", "commands": ["format c:"], "count": 3}]}]
    run({"name": "x", "action": "protocol", "protocol": "Взлом"}, "", cfg, s)
    assert [c[1] for c in j if c[0] == "open_console"] == list(CMD.HACKER_COMMANDS[:3])


@pytest.mark.parametrize("entry", [p["name"] for p in P.DEFAULTS["protocols"]])
def test_one_failing_step_does_not_stop_the_rest(cfg, rig, entry):
    proto = next(p for p in P.parse(P.DEFAULTS) if p.name == entry)
    first = proto.steps[0].name
    fail = {"media_pause": "media", "launch_workspace": "launch", "close_apps": "close_apps", "close_all": "close_windows", "hacker_windows": "open_console"}[first]
    j, s, ctl = rig(fail={fail}); cfg["workspace"] = ["a", "b"]; cfg["close_apps"] = ["telegram"]
    run_ = CMD.run_steps(CommandContext("", cfg, "wake_word", False, s), proto, None)
    assert run_.failed and fail in names(j)
    expected_after = {"Спящая красавица": "cancel_repeats", "Негры пашут": "media", "Бобик сдох": "lock", "Взлом Пентагона": "open_console"}[entry]
    assert names(j)[-1] == expected_after  # the last step still ran


def test_unknown_step_is_skipped(cfg, rig):
    j, s, _ = rig()
    cfg["protocols"] = [{"name": "Тест", "phrases": ["протокол тест"], "steps": ["warp_drive", "beep", "lock"]}]
    run({"name": "x", "action": "protocol", "protocol": "Тест"}, "", cfg, s)
    assert names(j) == ["lock"] and s.beeps == 1 and s.said == [P.DEFAULT_REPLY]


def test_test_turn_against_the_real_desktop_runs_no_step(cfg, tmp_path):
    from jarvis.adapters.system import SystemBackend
    j = Journal(); ctl = build_controller(tmp_path / "h", backend=SystemBackend())
    s = FakeServices(controller=ctl, sleep=Sleep(j), proactive=Proactive(j))
    run({"name": "x", "action": "protocol", "protocol": "Взлом Пентагона"}, "", cfg, s, test=True)
    run({"name": "x", "action": "protocol_cancel"}, "", cfg, s, test=True)
    assert j == [] and s.said == ["Доступ получен, сэр.", CMD.CANCELLED]


def test_protocol_list(cfg, rig):
    _, s, _ = rig(); run({"name": "protocol_list", "action": "protocol_list"}, "", cfg, s)
    assert s.said == ["Протоколы: Спящая красавица, Негры пашут, Бобик сдох, Взлом Пентагона, сэр."]
    cfg2 = copy.deepcopy(cfg); cfg2["protocols"] = []
    run({"name": "protocol_list", "action": "protocol_list"}, "", cfg2, s); assert s.said[-1] == CMD.NONE_CONFIGURED


def test_shutdown_still_confirms_through_the_same_gate(cfg, rig):
    clock = [0.0]; _, s, ctl = rig(clock=lambda: clock[0])
    ctl.execute({"cmd": "shutdown_prepare", "seconds": 600}, "", cfg, s.say, lambda *a, **k: None)
    assert ctl.pending["kind"] == "shutdown"
    answer = ctl.confirmation("да", "followup", 1.0)
    assert answer["approved"] and answer["seconds"] == 600 and answer["kind"] == "shutdown"


# ------------------------------------------------------------ sleep mode: only timers and the alarm sound
def test_in_sleep_only_timers_and_the_alarm_sound(app, cfg, monkeypatch, tmp_path):
    import datetime
    from jarvis.adapters.audio import ClapDetector
    from jarvis.adapters.proactive import Manager
    from jarvis.app import listener as L
    now = datetime.datetime(2030, 1, 7, 8, 0).timestamp()
    started = []
    monkeypatch.setattr(app.listener, "start", lambda trig, **kw: started.append((trig, kw.get("text"))))
    pm = Manager(tmp_path / "pm", clock=lambda: now, input_reader=lambda n: n - 1)
    (tmp_path / "pm" / "outbox").mkdir(parents=True)
    note = tmp_path / "pm" / "outbox" / "proactive-note.txt"; note.write_text("Серверное объявление.", encoding="utf-8")
    os.utime(note, (now - 5, now - 5))
    pm.state["pending"].append({"key": "calendar:x", "text": "Сэр, скоро встреча.", "expires": now + 600, "kind": "calendar"})
    pm.state["last_spoken"] = 0
    sleep = app.c.sleep.get(); sleep.clock = lambda: now; sleep.start(4 * 3600)
    timers = app.c.controller.get().timers
    for kind in ("notice", "reminder", "timer"): timers.add(1, kind, kind=kind)
    timers.clock = lambda: time.time() + 60
    lp = L.Loop(cfg=cfg, pm=pm, oww=None, clap=ClapDetector())
    for _ in range(4):
        lp.next_proactive = 0; app.listener._housekeeping(lp)
        for trig, item in started:
            if trig == "proactive": pm.complete(item)
    kinds = [(t, x.get("entry") or x.get("kind")) for t, x in started]
    assert ("proactive", "wake_up") in kinds and ("timer_fire", "timer") in kinds
    assert all(k in (("proactive", "wake_up"), ("timer_fire", "timer")) for k in kinds), kinds
    assert note.exists()  # the server notice waits for the wake-up


def test_spoken_yes_reaches_the_protocol_through_the_conversation(app, cfg, monkeypatch):
    j = Journal(); ctl = app.conversation.controller(); ctl.backend = Backend(j); said = []
    monkeypatch.setattr(app.conversation, "say", lambda text, cfg, **kw: said.append(text) or True)
    ctl.ask("protocol", cfg, protocol="Бобик сдох", seconds=None)
    st = app.c.state; st.last_input_conf = 0.95; st.last_input_end = ctl.clock()
    app.conversation.handle_turn("followup", None, "да", False, 0.0)
    assert names(j) == ["close_windows", "minimize_all", "media", "lock"] and said[-1] == "Бобик сдох, сэр."


def test_close_apps_step_still_closes_a_named_list(cfg, rig):
    j, s, _ = rig(); cfg["close_apps"] = ["telegram", "chrome"]
    cfg["protocols"] = [{"name": "Тест", "phrases": ["протокол тест"], "steps": ["close_apps"]}]
    run({"name": "x", "action": "protocol", "protocol": "Тест"}, "", cfg, s)
    assert j[0][:2] == ("close_apps", ("telegram", "chrome")) and os.getpid() in j[0][2]


# ------------------------------------------------------------ the owner's local (gitignored) protocol file
LOCAL = {"extend": {"Взлом Пентагона": {"steps": [{"step": "launch_tracked", "targets": ["C:/private/one.cmd", "C:/private/two.cmd"]}]}},
         "protocols": [{"name": "Личный", "phrases": ["протокол личный"], "steps": ["beep"]}]}


def test_merge_local_extends_and_adds():
    merged = P.merge_local(copy.deepcopy(P.DEFAULTS["protocols"]), LOCAL)
    hack = next(p for p in merged if p["name"] == "Взлом Пентагона")
    assert hack["steps"] == ["hacker_windows", LOCAL["extend"]["Взлом Пентагона"]["steps"][0]]
    assert merged[-1]["name"] == "Личный" and P.DEFAULTS["protocols"][3]["steps"] == ["hacker_windows"]  # defaults untouched
    assert P.merge_local(P.DEFAULTS["protocols"], None) == P.DEFAULTS["protocols"]
    assert P.merge_local(P.DEFAULTS["protocols"], {"extend": "junk", "protocols": "junk"}) == P.DEFAULTS["protocols"]


def test_settings_read_the_local_file(tmp_path, caplog):
    import json
    from jarvis.app import settings
    home = tmp_path / "home"; (home / "secrets").mkdir(parents=True)
    (home / "secrets" / "protocols.local.json").write_text(json.dumps(LOCAL, ensure_ascii=False), encoding="utf-8")
    cfg = settings.config_store(home).load()
    assert any(s == LOCAL["extend"]["Взлом Пентагона"]["steps"][0] for p in cfg["protocols"] if p["name"] == "Взлом Пентагона" for s in p["steps"])
    assert any(a["name"] == "protocol_личный" for a in cfg["aliases"]) and "private" not in caplog.text
    (home / "secrets" / "protocols.local.json").write_text("{broken", encoding="utf-8")
    cfg = settings.config_store(home).load()
    assert next(p for p in cfg["protocols"] if p["name"] == "Взлом Пентагона")["steps"] == ["hacker_windows"]
    assert "local protocol file unreadable" in caplog.text and "private" not in caplog.text


class TrackedBackend(Backend):
    def open_window(self, target): self._do("open_window", target); self.pid += 1; return self.pid


def test_local_server_windows_open_and_cancel_closes_them(cfg, tmp_path, caplog):
    j = Journal(); b = TrackedBackend(j); ctl = build_controller(tmp_path / "h", backend=b)
    s = FakeServices(controller=ctl, sleep=Sleep(j), proactive=Proactive(j))
    cfg["protocols"] = P.merge_local(cfg["protocols"], LOCAL)
    run({"name": "x", "action": "protocol", "protocol": "Взлом Пентагона"}, "", cfg, s)
    assert [c[1] for c in j if c[0] == "open_window"] == ["C:/private/one.cmd", "C:/private/two.cmd"]
    assert len(ctl.protocol_pids) == 8 and "private" not in caplog.text and s.said == ["Доступ получен, сэр."]
    j.clear(); run({"name": "protocol_cancel", "action": "protocol_cancel"}, "", cfg, s)
    assert [c[1] for c in j if c[0] == "end_process"] == list(range(101, 109)) and ctl.protocol_pids == []


def test_one_failing_server_window_does_not_stop_the_other(cfg, tmp_path):
    j = Journal(); b = TrackedBackend(j, fail={"open_window"}); ctl = build_controller(tmp_path / "h", backend=b)
    s = FakeServices(controller=ctl, sleep=Sleep(j), proactive=Proactive(j))
    cfg["protocols"] = [{"name": "Тест", "phrases": ["протокол тест"], "steps": [{"step": "launch_tracked", "targets": ["a", "b"]}, "lock"]}]
    run({"name": "x", "action": "protocol", "protocol": "Тест"}, "", cfg, s)
    assert names(j) == ["open_window", "open_window", "lock"] and ctl.protocol_pids == []
