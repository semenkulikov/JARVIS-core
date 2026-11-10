import datetime
import json
import logging

from jarvis.adapters.outbox import OutboxSignal
from jarvis.core.fuzzy import fuzzy_alias, norm
from jarvis.core.perf import Trace
from jarvis.core.phrases import template_phrases

ALIASES = {"aliases": [
    {"name": "status", "action": "status", "phrases": ["какой статус"]},
    {"name": "time", "action": "time", "phrases": ["сколько времени"]},
    {"name": "add", "action": "todoist_add", "phrases": ["добавь задачу"]},
]}


def test_trace_logs_each_event_once_and_one_summary(caplog):
    caplog.set_level(logging.INFO, logger="jarvis")
    t = Trace("text", request_id="r1")
    t.mark("asr", stt="vosk"); t.mark("asr"); t.finish("ok"); t.finish("again"); t.mark("late")
    rows = [r.getMessage() for r in caplog.records]
    assert sum(m.startswith("PERF summary") for m in rows) == 1
    summary = json.loads(next(m for m in rows if m.startswith("PERF summary")).split(" ", 2)[2])
    assert summary["result"] == "ok" and summary["stt"] == "vosk" and set(summary["events_ms"]) == {"wake", "asr", "done"}


def test_fuzzy_alias_is_read_only_and_conservative():
    assert norm("Ну, чё там, сэр?") == "что там"
    hit = fuzzy_alias("какой статусс", ALIASES)
    assert hit and hit["name"] == "status" and hit["_fuzzy"]
    assert fuzzy_alias("добавь задачу", ALIASES) is None
    assert fuzzy_alias("совсем другое", ALIASES) is None
    assert fuzzy_alias("какой статусс", {**ALIASES, "intent_fuzzy_enabled": False}) is None


def test_template_phrases_are_whole_sentences():
    out = template_phrases({"time_preload_minutes": 2}, datetime.datetime(2026, 1, 1, 9, 59))
    assert out[0] == "Сейчас девять часов пятьдесят девять минут, сэр." and out[1].startswith("Сейчас десять")
    assert "Таймер на пять минут, сэр." in out and out[-1] == "Таймер на один час, сэр."


def test_outbox_signal_polls_when_disabled(tmp_path):
    s = OutboxSignal(str(tmp_path))
    assert s.start(enabled=False) == "polling"
    s.event.set(); s.wait({"outbox_poll_s": 5}); s.stop()
