import datetime as dt

import pytest

import jarvis_tasks as T

NOW = dt.datetime(2026, 11, 10, 14, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))


@pytest.mark.parametrize("text,mode", [
    ("утренний брифинг", "briefing"), ("брифинг", "briefing"), ("утренняя сводка", "briefing"), ("дай утренний брифинг", "briefing"),
    ("чё ещё осталось", "left"), ("че еще осталось", "left"), ("что ещё осталось", "left"), ("что осталось", "left"),
    ("что мне ещё осталось сделать", "left"), ("что ещё надо сделать сегодня", "left"), ("сколько задач осталось", "left"),
    ("есть что ещё осталось", "left"), ("а что ещё осталось на сегодня", "left"),
    ("перескажи все задачи", "all"), ("перескажу все задачи", "all"), ("перескажу все раздачи", "all"),
    ("задачи все перескажи", "all"), ("задачи все перескажу", "all"), ("все задачи", "all"), ("расскажи все задачи", "all"),
    ("перечисли все мои задачи", "all"), ("список всех задач", "all"), ("назови все задачи на сегодня", "all"),
    ("что по ноушену", "notion"), ("задачи по проектам", "notion"), ("что по задачам по проектам", "notion"),
    ("что нужно сделать по проектам", "notion"), ("что в notion", "notion"),
])
def test_task_intents(text, mode):
    assert T.intent(text) == {"name": "tasks_" + mode, "action": "tasks", "mode": mode}


@pytest.mark.parametrize("text", ["проснись", "джарвис проснись", "есть проснись", "просыпайся"])
def test_awake_intent(text):
    assert T.intent(text)["action"] == "awake"


@pytest.mark.parametrize("text", ["отметь все задачи выполненными", "добавь задачу купить хлеб", "удали все задачи",
                                  "что осталось от торта в холодильнике", "статус по задачам", "открой браузер", "старых", "крыс"])
def test_not_task_intents(text):
    assert T.intent(text) is None


CACHE = {"updated": "2026-11-10T13:30:00+01:00", "text": "Данные на 13:30, сэр. Сводка дня.", "today": "Сегодня одна встреча.",
         "tasks": [{"title": "Коммит в GitHub", "due_iso": "2026-11-10T15:00:00+01:00"},
                   {"title": "Прочитать статью", "done": True},
                   {"title": "Курс по Python", "due_iso": "2026-11-09", "overdue": True}],
         "notion_tasks": [{"project": "Лендинг", "status": "В работе", "open_subtasks": ["форма", "тексты"], "updated_iso": None},
                          {"project": "Бот", "status": "На проверке", "open_subtasks": None}],
         "notion": "В Notion два проекта в работе."}


def test_all_tasks_read_with_times():
    reply, _ = T.answer("all", CACHE, True, NOW)
    assert reply.startswith("Всего три задачи, сэр.")
    assert "Коммит в GitHub — в 15:00" in reply and "Курс по Python — просрочена" in reply and "Прочитать статью" in reply


def test_left_skips_done_and_adds_notion():
    reply, _ = T.answer("left", CACHE, True, NOW)
    assert reply.startswith("Осталось две задачи, сэр.") and "Прочитать статью" not in reply
    assert "Лендинг, в работе: осталось форма, тексты" in reply and "Бот, на проверке" in reply


def test_left_falls_back_to_today_and_notion_text():
    cache = {"today": "Сегодня одна встреча.", "notion": "В Notion два проекта в работе.", "notion_tasks": None}
    assert T.answer("left", cache, True, NOW)[0] == "Сегодня одна встреча. В Notion два проекта в работе."


def test_missing_or_stale_fields_go_to_server():
    assert T.answer("all", {"today": "x"}, True, NOW) == (None, T.SERVER_TEXT["all"])
    assert T.answer("notion", {"notion": None, "notion_tasks": "bad"}, True, NOW)[0] is None
    assert T.answer("left", CACHE, False, NOW)[0] is None
    assert T.answer("briefing", None, True, NOW)[0] is None


def test_briefing_from_cache_with_stamp():
    reply, _ = T.answer("briefing", CACHE, True, NOW, stamp="Данные на 13:30.")
    assert reply == "Утренний брифинг, сэр. Данные на 13:30. Сводка дня. В Notion два проекта в работе."


def test_notion_tolerates_junk_items():
    cache = {"notion_tasks": [None, {"project": ""}, {"project": "Сайт", "open_subtasks": [None, "логотип"]}]}
    assert T.answer("notion", cache, True, NOW)[0] == "По проектам в Notion, сэр. Сайт: осталось логотип."
