"""Fixed-time schedule (config ``schedule``): alarm, Grok briefing and bedtime with fake clocks and fake
services only. Nothing real is played, posted or changed (see conftest guards)."""
import copy
import datetime
import json
import os
import sys
import time

import pytest

from jarvis.adapters.proactive import Manager
from jarvis.core import proactive as P
from jarvis.core import timetable as T


def at(hour, minute=0, day=1, month=1, year=2030):
    return datetime.datetime(year, month, day, hour, minute).timestamp()


def config(**over):
    cfg = dict(P.DEFAULTS, schedule=copy.deepcopy(T.DEFAULTS["schedule"]), server_down_wait_s=45)
    cfg.update(over); return cfg


class Clock:
    def __init__(self, t): self.t = t; self.input = None
    def __call__(self): return self.t
    def last_input(self, now): return now - 3600 if self.input is None else self.input


def manager(home, clock):
    (home / "outbox").mkdir(parents=True, exist_ok=True)
    return Manager(home, clock=clock, input_reader=clock.last_input)


def run(m, cfg, sleeping=False):
    """One tick plus take; returns (briefing job or None, item or None)."""
    job = m.tick(cfg, True); item = m.take(cfg, sleeping=sleeping)
    return job, item


def answer(m, job, text="План на день: в десять созвон, в 16:30 тренировка.", age=1.0):
    p = m.outbox / job["outbox_file"]; p.write_text(text, encoding="utf-8")
    os.utime(p, (m.clock() - age, m.clock() - age)); m.morning_result(job, True, {})
    return p


# ------------------------------------------------------------ parsing
def test_default_entries_and_briefing_follows_the_alarm():
    es = {e.id: e for e in T.parse(T.DEFAULTS)}
    assert es["wake_up"].minute == 8 * 60 and es["wake_up"].volume == 100 and es["wake_up"].override_quiet
    assert es["morning_briefing"].minute == 9 * 60 and es["morning_briefing"].prefetch_min == 10
    assert es["bedtime"].max_repeats == 1 and es["bedtime"].repeat_after_min == 15


def test_bad_entries_are_skipped_not_the_section(caplog):
    cfg = {"schedule": [{"id": "b", "kind": "briefing", "after": "a", "delay_min": 30},  # follows an entry listed later
                        {"id": "a", "time": "07:30", "say": ["Подъём."]},
                        {"id": "x", "time": "25:00", "say": ["нет"]}, {"id": "y", "time": "10:00", "kind": "say"},
                        {"id": "z", "kind": "briefing", "after": "nobody"}, {"id": "v", "time": "09:00", "say": ["x"], "volume": 140},
                        {"id": "off", "time": "09:00", "say": ["x"], "enabled": False}, "junk"]}
    assert {e.id: e.minute for e in T.parse(cfg)} == {"a": 450, "b": 480}
    assert "'z' skipped: unknown after" in caplog.text and "'v' skipped: bad volume" in caplog.text


def test_day_fields():
    f = T.day_fields(at(8, 50, day=4), {})  # 2030-01-04 is a Friday
    assert f["weekday"] == "пятница" and f["local_date"] == "2030-01-04" and f["local_time"].startswith("2030-01-04T08:50:00")
    assert datetime.datetime.fromisoformat(f["local_time"]).tzinfo is not None and f["timezone"]


# ------------------------------------------------------------ alarm
def test_alarm_at_eight_once_through_quiet_hours_dnd_and_sleep(tmp_path):
    clock = Clock(at(7, 59)); m = manager(tmp_path, clock); cfg = config(proactive_quiet_end="09:00"); m.set_dnd(True)
    assert run(m, cfg, sleeping=True) == (None, None)
    clock.t = at(8, 0)
    _, item = run(m, cfg, sleeping=True)
    assert item["kind"] == "schedule" and item["volume"] == 100 and item["text"] == T.DEFAULTS["schedule"][0]["say"][0]
    m.complete(item); clock.t = at(8, 3)
    assert run(m, cfg, sleeping=True) == (None, None)
    clock.t = at(8, 5); assert run(manager(tmp_path, clock), cfg, sleeping=True)[1] is None  # restart: not again


@pytest.mark.parametrize("start,sounds", [((8, 5), True), ((8, 9), True), ((8, 10), False), ((8, 40), False), ((10, 0), False)])
def test_alarm_after_a_late_start_only_within_late_skip(tmp_path, start, sounds):
    clock = Clock(at(*start)); m = manager(tmp_path, clock)
    _, item = run(m, config())
    assert (item is not None and item.get("entry") == "wake_up") is sounds


# ------------------------------------------------------------ briefing
def test_briefing_prefetched_at_8_50_and_read_at_9_without_waiting(tmp_path):
    clock = Clock(at(8, 49)); m = manager(tmp_path, clock); cfg = config(schedule=[e for e in T.DEFAULTS["schedule"] if e["id"] != "bedtime"])
    m.state["done"]["schedule:wake_up:2030-01-01:0"] = clock.t
    assert run(m, cfg) == (None, None)
    clock.t = at(8, 50); job, item = run(m, cfg)
    assert item is None and job["kind"] == "morning_briefing" and job["trigger"] == "schedule"
    assert job["style"] == "plan_and_recommendations" and job["weekday"] == "вторник" and job["local_time"].startswith("2030-01-01T08:50")
    assert job["reply_mode"] == "proactive" and job["outbox_file"] == "proactive-" + job["request_id"] + ".txt"
    assert datetime.datetime.fromisoformat(job["expires_iso"]).timestamp() == at(12)
    clock.t = at(8, 52); answer(m, job)
    clock.t = at(8, 55); assert run(m, cfg) == (None, None)  # held until its time, not read as a plain outbox file
    clock.t = at(9, 0); again, item = run(m, cfg)
    assert again is None and item["text"].startswith("План на день") and item["kind"] == "schedule"
    m.complete(item)
    assert not (m.outbox / job["outbox_file"]).exists() and (m.outbox / "done" / (job["outbox_file"] + ".spoken")).exists()
    clock.t = at(9, 30); m2 = manager(tmp_path, clock)
    assert run(m2, cfg) == (None, None)  # restart: no second request, no second briefing
    late = m2.outbox / job["outbox_file"]; late.write_text("Поздний ответ.", encoding="utf-8"); os.utime(late, (clock.t - 5, clock.t - 5))
    assert run(m2, cfg) == (None, None) and (m2.outbox / "done" / (job["outbox_file"] + ".late")).exists()


def test_alarm_moved_to_7_30_moves_the_briefing_to_8_30(tmp_path):
    sched = copy.deepcopy(T.DEFAULTS["schedule"]); sched[0]["time"] = "07:30"
    clock = Clock(at(8, 19)); m = manager(tmp_path, clock); cfg = config(schedule=sched[1:2] + sched[:1])
    assert m.tick(cfg, True) is None
    clock.t = at(8, 20); job = m.tick(cfg, True); assert job
    answer(m, job); clock.t = at(8, 30)
    assert run(m, cfg)[1]["entry"] == "morning_briefing"


def test_started_at_8_40_skips_the_alarm_and_briefs_at_9(tmp_path):
    clock = Clock(at(8, 40)); m = manager(tmp_path, clock); cfg = config()
    assert run(m, cfg) == (None, None)  # no alarm, the briefing request waits for 08:50
    clock.t = at(8, 50); job = m.tick(cfg, True); assert job and job["trigger"] == "schedule"
    answer(m, job); clock.t = at(9, 0)
    assert run(m, cfg)[1]["entry"] == "morning_briefing"


def test_started_at_10_briefs_at_the_first_activity(tmp_path):
    clock = Clock(at(10, 0)); m = manager(tmp_path, clock); cfg = config()
    job, item = run(m, cfg); assert item is None and job
    answer(m, job); clock.t = at(10, 1); clock.input = at(9, 59)
    assert run(m, cfg)[1] is None  # nobody at the laptop yet
    clock.t = at(10, 20); clock.input = at(10, 19)
    item = run(m, cfg)[1]
    assert item["entry"] == "morning_briefing" and item["text"].startswith("План")


def test_laptop_asleep_at_nine_waits_for_activity(tmp_path):
    clock = Clock(at(8, 50)); m = manager(tmp_path, clock); cfg = config()
    m.state["done"]["schedule:wake_up:2030-01-01:0"] = clock.t
    job = m.tick(cfg, True); answer(m, job)
    clock.t = at(9, 40); clock.input = at(8, 45)
    assert run(m, cfg)[1] is None
    clock.input = at(9, 41); clock.t = at(9, 41)
    assert run(m, cfg)[1]["entry"] == "morning_briefing"


def test_briefing_waits_for_sleep_dnd_and_quiet_then_drops_at_catch_up(tmp_path):
    clock = Clock(at(8, 50)); m = manager(tmp_path, clock); cfg = config()
    m.state["done"]["schedule:wake_up:2030-01-01:0"] = clock.t
    answer(m, m.tick(cfg, True)); clock.t = at(9, 0)
    assert run(m, cfg, sleeping=True)[1] is None
    m.set_dnd(True); assert run(m, cfg)[1] is None
    m.set_dnd(False); clock.t = at(12, 0); assert run(m, cfg)[1] is None and not m.state["pending"]


def test_server_silent_gives_the_fallback_after_the_wait(tmp_path):
    clock = Clock(at(8, 50)); m = manager(tmp_path, clock); cfg = config()
    m.state["done"]["schedule:wake_up:2030-01-01:0"] = clock.t
    job = m.tick(cfg, True); m.morning_result(job, False, cfg)
    clock.t = at(8, 51); assert m.tick(cfg, True) is None  # retry only after morning_retry_s
    clock.t = at(8, 52); retry = m.tick(cfg, True); assert retry and retry["request_id"] == job["request_id"]
    m.morning_result(retry, False, cfg)
    clock.t = at(9, 0); assert run(m, cfg)[1] is None
    clock.t = at(9, 0) + 46; item = run(m, cfg)[1]
    assert item["fallback"] and item["entry"] == "morning_briefing"


def test_old_presence_briefing_stays_off_by_default():
    assert P.DEFAULTS["morning_briefing_enabled"] is False


# ------------------------------------------------------------ bedtime
def test_bedtime_and_one_repeat(tmp_path):
    clock = Clock(at(22, 0)); m = manager(tmp_path, clock); cfg = config()
    first = run(m, cfg)[1]; assert first["entry"] == "bedtime" and first["repeat"] == 0 and first.get("volume") is None
    m.complete(first); clock.t = at(22, 14); assert run(m, cfg)[1] is None
    clock.t = at(22, 15); second = run(m, cfg)[1]; assert second["repeat"] == 1
    m.complete(second); clock.t = at(22, 31); assert run(m, cfg)[1] is None
    clock.t = at(22, 46); assert run(m, cfg)[1] is None


@pytest.mark.parametrize("dnd,sleeping", [(True, False), (False, True)])
def test_bedtime_silent_in_dnd_and_sleep(tmp_path, dnd, sleeping):
    clock = Clock(at(22, 0)); m = manager(tmp_path, clock); cfg = config(); m.set_dnd(dnd)
    for minute in range(0, 40, 1):
        clock.t = at(22, minute); assert run(m, cfg, sleeping=sleeping)[1] is None


def test_cancel_repeats_drops_the_bedtime_repeat(tmp_path):
    clock = Clock(at(22, 0)); m = manager(tmp_path, clock); cfg = config()
    m.complete(run(m, cfg)[1]); assert m.cancel_repeats(cfg) == 2  # today's and yesterday's repeat keys
    clock.t = at(22, 15); assert run(m, cfg)[1] is None


def test_next_alarm(tmp_path):
    clock = Clock(at(23, 0)); m = manager(tmp_path, clock)
    assert m.next_at(config(), "wake_up") == at(8, 0, day=2) and m.next_at(config(), "nobody") is None


def test_weekday_entry(tmp_path):
    cfg = config(schedule=[{"id": "skills", "time": "11:00", "weekdays": [5], "say": ["Сэр, время навыков."]}])
    clock = Clock(at(11, 0, day=4)); m = manager(tmp_path, clock); assert run(m, cfg)[1] is None  # Friday
    clock.t = at(11, 0, day=5); assert run(m, cfg)[1]["entry"] == "skills"


def test_schedule_items_skip_the_min_interval(tmp_path):
    clock = Clock(at(22, 0)); m = manager(tmp_path, clock); cfg = config(); m.state["last_spoken"] = clock.t - 5
    assert run(m, cfg)[1]["entry"] == "bedtime"


# ------------------------------------------------------------ DST and restart
needs_tz = pytest.mark.skipif(sys.platform == "win32" or not hasattr(time, "tzset"), reason="TZ switching needs tzset")


@pytest.fixture
def belgrade(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Belgrade"); time.tzset()
    yield
    monkeypatch.undo(); time.tzset()


@needs_tz
@pytest.mark.parametrize("month,day", [(3, 31), (10, 27)])  # 2030 spring forward / fall back
def test_dst_days_fire_once_at_wall_time(tmp_path, belgrade, month, day):
    cfg = config(schedule=[{"id": "night", "time": "02:30", "say": ["Ночь."], "override_quiet": True},
                           {"id": "wake_up", "time": "08:00", "say": ["Подъём."], "override_quiet": True}])
    start = at(0, 0, day, month); clock = Clock(start); spoken = []; m = manager(tmp_path, clock)
    for k in range(0, 10 * 3600, 30):  # every 30 s of real elapsed time, through the DST jump
        clock.t = start + k
        if k % 3600 == 0: m = manager(tmp_path, clock)  # and a restart every hour
        item = run(m, cfg, sleeping=True)[1]
        if item: spoken.append((item["entry"], datetime.datetime.fromtimestamp(clock.t).strftime("%H:%M"))); m.complete(item)
    assert [e for e, _ in spoken] == ["night", "wake_up"]
    assert spoken[1][1] == "08:00"


@needs_tz
def test_briefing_after_spring_forward_is_still_an_hour_after_the_alarm(tmp_path, belgrade):
    e = {x.id: x for x in T.parse(T.DEFAULTS)}
    day = datetime.date(2030, 3, 31)
    assert e["morning_briefing"].at(day) - e["wake_up"].at(day) == 3600
    assert datetime.datetime.fromtimestamp(e["wake_up"].at(day)).strftime("%H:%M") == "08:00"


def test_state_file_keeps_done_keys(tmp_path):
    clock = Clock(at(8, 0)); m = manager(tmp_path, clock); m.complete(run(m, config())[1])
    state = json.loads((tmp_path / "cache" / "proactive_state.json").read_text(encoding="utf-8"))
    assert "schedule:wake_up:2030-01-01:0" in state["done"]


# ------------------------------------------------------------ the spoken turn (fake backend, fake voice)
class Backend:
    is_fake = True
    def __init__(self, level=35.0): self.level = level; self.calls = []
    def output_volume(self): return self.level
    def volume(self, v): self.calls.append(v); self.level = v


class Ctl:
    def __init__(self, backend): self.backend = backend


def test_alarm_turn_raises_and_restores_volume_and_opens_no_followup_in_sleep(app, cfg, monkeypatch):
    conv = app.conversation; b = Backend(); said = []
    monkeypatch.setattr(conv, "controller", lambda: Ctl(b))
    monkeypatch.setattr(conv, "say", lambda text, cfg, **kw: said.append((text, b.level)) or True)
    sleep = app.c.sleep.get(); sleep.start(3600)
    item = {"key": "schedule:wake_up:x:0", "kind": "schedule", "text": "Подъём!", "volume": 100, "expires": time.time() + 60}
    conv._event_turn("proactive", item, cfg, test=True)
    assert said == [("Подъём!", 100)] and b.calls == [100, 35.0] and app.c.state.followup_eligible is False


def test_briefing_fallback_turn_uses_the_snapshot(app, cfg, monkeypatch):
    conv = app.conversation; said = []
    monkeypatch.setattr(conv, "say", lambda text, cfg, **kw: said.append(text) or True)
    monkeypatch.setattr(app.c.status, "cached_status", lambda field, cfg: ("fresh", "По данным на девять, сэр. Три задачи.", 0.1))
    conv._event_turn("proactive", {"key": "k", "kind": "schedule", "fallback": True, "expires": None}, cfg, test=True)
    assert said == [T.FALLBACK_PHRASE + " По данным на девять, сэр. Три задачи."] and app.c.state.followup_eligible is True
    monkeypatch.setattr(app.c.status, "cached_status", lambda field, cfg: ("old", "x", 9.0))
    conv._event_turn("proactive", {"key": "k", "kind": "schedule", "fallback": True, "expires": None}, cfg, test=True)
    assert said[-1] == T.FALLBACK_PHRASE + " " + T.NO_SNAPSHOT_PHRASE


def test_schedule_request_goes_out_with_its_fields(app, cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(app.c.transport, "call", lambda rid, text, trig, cfg, test, **kw: calls.append((rid, text, trig, kw)) or True)
    job = {"request_id": "r1", "kind": "morning_briefing", "trigger": "schedule", "schedule_key": "schedule:b:d:0", "style": "plan_and_recommendations",
           "local_time": "2030-01-01T08:50:00+01:00", "weekday": "вторник", "outbox_file": "proactive-r1.txt", "reply_mode": "proactive"}
    app.conversation.request_morning(job, cfg, test=True)
    rid, text, trig, kw = calls[0]
    assert rid == "r1" and trig == "schedule" and kw["kind"] == "morning_briefing" and "план" in text.lower()
    assert kw["extra_payload"]["style"] == "plan_and_recommendations" and "trigger" not in kw["extra_payload"] and "schedule_key" not in kw["extra_payload"]
