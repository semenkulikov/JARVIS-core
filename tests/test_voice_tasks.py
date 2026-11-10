import json

import jarvis_tasks as T
from jarvis.core import routing as ROUTING


def _cache(listener, tmp_path, monkeypatch, data):
    p = tmp_path / "status.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(listener, "CACHE", str(p))


def test_run_tasks_reads_fresh_cache(listener, cfg, monkeypatch, tmp_path):
    now = listener.datetime.datetime.now().astimezone()
    _cache(listener, tmp_path, monkeypatch, {"updated": now.isoformat(timespec="seconds"), "today": "Сегодня одна встреча.",
                                             "notion": "В Notion один проект на проверке."})
    said, posted = [], []
    monkeypatch.setattr(listener, "say_reply", lambda t, c, **k: said.append(t))
    monkeypatch.setattr(listener, "free_phrase", lambda *a, **k: posted.append((a, k)))
    listener.run_tasks("left", "что ещё осталось", cfg, "wake_word", False)
    assert said and said[0].startswith("Данные на ") and said[0].endswith("Сегодня одна встреча. В Notion один проект на проверке.")
    assert not posted


def test_run_tasks_without_task_list_asks_server(listener, cfg, monkeypatch, tmp_path):
    now = listener.datetime.datetime.now().astimezone()
    _cache(listener, tmp_path, monkeypatch, {"updated": now.isoformat(timespec="seconds"), "today": "x"})
    posted = []
    monkeypatch.setattr(listener, "say_reply", lambda t, c, **k: posted.append(("said", t)))
    monkeypatch.setattr(listener, "free_phrase", lambda text, cfg, trig, test, **k: posted.append((text, k)))
    listener.run_tasks("all", "все задачи", cfg, "wake_word", False)
    text, kw = posted[0]
    assert text == T.SERVER_TEXT["all"] and kw["extra_payload"] == {"intent": "tasks_all"} and kw["kind"] == "free"


def test_run_tasks_missing_cache_file(listener, cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(listener, "CACHE", str(tmp_path / "none.json"))
    posted = []
    monkeypatch.setattr(listener, "free_phrase", lambda text, *a, **k: posted.append(text))
    listener.run_tasks("briefing", "утренний брифинг", cfg, "wake_word", False)
    assert posted == [T.SERVER_TEXT["briefing"]]


def test_awake_and_capabilities_reply_locally(listener, cfg, monkeypatch):
    said = []
    monkeypatch.setattr(listener, "say", lambda t, c, **k: said.append(t) or True)
    monkeypatch.setattr(listener, "say_reply", lambda t, c, **k: said.append(t))
    listener.run_alias(ROUTING.match_alias("проснись", cfg), "проснись", cfg, "wake_word", False)
    listener.run_alias(ROUTING.match_alias("что ты умеешь", cfg), "что ты умеешь", cfg, "wake_word", False)
    assert said[0] == T.AWAKE_REPLY and said[1].startswith("Умею вот что, сэр:")


def test_grammar_has_new_phrases(listener, cfg):
    g = ROUTING.grammar_phrases(cfg)
    assert "утренний брифинг" in g and "что ещё осталось" in g and "выруби экран" in g and "что ты умеешь" in g
