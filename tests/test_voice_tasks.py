import datetime
import json

from jarvis.core import tasks as T
from jarvis.core import routing as ROUTING
from jarvis.adapters.status_cache import StatusCache
from command_fakes import FakeServices, run


def _cache(tmp_path, data):
    p = tmp_path / "status.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return StatusCache(str(p))


def test_run_tasks_reads_fresh_cache(cfg, tmp_path):
    now = datetime.datetime.now().astimezone()
    s = FakeServices(_cache(tmp_path, {"updated": now.isoformat(timespec="seconds"), "today": "Сегодня одна встреча.",
                                       "notion": "В Notion один проект на проверке."}))
    run({"action": "tasks", "mode": "left"}, "что ещё осталось", cfg, s)
    assert s.replies and s.replies[0].startswith("Данные на ") and s.replies[0].endswith("Сегодня одна встреча. В Notion один проект на проверке.")
    assert not s.asked


def test_run_tasks_without_task_list_asks_server(cfg, tmp_path):
    now = datetime.datetime.now().astimezone()
    s = FakeServices(_cache(tmp_path, {"updated": now.isoformat(timespec="seconds"), "today": "x"}))
    run({"action": "tasks", "mode": "all"}, "все задачи", cfg, s)
    text, kw = s.asked[0]
    assert not s.replies
    assert text == T.SERVER_TEXT["all"] and kw["extra_payload"] == {"intent": "tasks_all"} and kw["kind"] == "free" and kw["ack"] == "<ack_lookup>"


def test_run_tasks_missing_cache_file(cfg, tmp_path):
    s = FakeServices(StatusCache(str(tmp_path / "none.json")))
    run({"action": "tasks", "mode": "briefing"}, "утренний брифинг", cfg, s)
    assert [t for t, _ in s.asked] == [T.SERVER_TEXT["briefing"]]


def test_awake_and_capabilities_reply_locally(app, cfg, monkeypatch):
    said = []
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: said.append(t) or True)
    monkeypatch.setattr(app.conversation, "say_reply", lambda t, c, **k: said.append(t))
    app.conversation.run_alias(ROUTING.match_alias("проснись", cfg), "проснись", cfg, "wake_word", False)
    app.conversation.run_alias(ROUTING.match_alias("что ты умеешь", cfg), "что ты умеешь", cfg, "wake_word", False)
    assert said[0] == T.AWAKE_REPLY and said[1].startswith("Умею вот что, сэр:")


def test_grammar_has_new_phrases(app, cfg):
    g = ROUTING.grammar_phrases(cfg)
    assert "утренний брифинг" in g and "что ещё осталось" in g and "выруби экран" in g and "что ты умеешь" in g
