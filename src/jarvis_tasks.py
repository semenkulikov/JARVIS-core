"""Local task questions: morning briefing, what is left today, all tasks, Notion projects.

intent() maps a transcript (already wake-stripped) to a route; answer() builds the spoken reply
from cache/status.json when the snapshot has what is needed, otherwise returns the request for
the server. Every cache field is optional: a missing or malformed field just means "ask the
server". Pure module: no audio, no I/O.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import List, Optional, Tuple

import jarvis_text as JT
import jarvis_vocab as VOCAB

_LEAD = r"^(?:(?:а|ну|и|так|слушай|скажи|джарвис|то есть|есть)\s+)*"
_MUTATE = re.compile(r"\b(?:отмет\w*|выполн\w*|заверш\w*|закр\w*|добав\w*|созда\w*|удал\w*|постав\w*|перенес\w*|измен\w*)\b")
_TASK = r"(?:за|раз)дач\w*"
_RETELL = r"(?:перескаж\w*|расскаж\w*|перечисл\w*|назови|прочитай|зачитай|озвучь|покажи|скажи)"

BRIEFING = re.compile(r"\bбрифинг\w*\b|\bутренн\w* (?:сводк\w*|отчет\w*|доклад\w*)\b")
LEFT = re.compile(_LEAD + r"(?:что|че|чо|чего|шо|що)\s+(?:же\s+)?(?:еще\s+)?(?:там\s+)?(?:у меня\s+|у нас\s+|мне\s+)?(?:еще\s+)?"
                  r"остал\w*(?:\s+(?:сделать|на сегодня|сегодня|по задачам|из задач))?$"
                  r"|" + _LEAD + r"что (?:еще )?(?:надо|нужно) (?:сделать|успеть)(?: сегодня)?$"
                  r"|" + _LEAD + r"сколько (?:еще )?" + _TASK + r" остал\w*")
ALL = re.compile(_LEAD + r"(?:" + _RETELL + r"\s+)?(?:мне\s+)?(?:все|всех|весь список)\s+(?:мои\s+|моих\s+)?" + _TASK +
                 r"(?:\s+на сегодня)?(?:\s+" + _RETELL + r")?$|" + _LEAD + _TASK + r"\s+все\s+" + _RETELL + r"$|" +
                 _LEAD + _RETELL + r"\s+" + _TASK + r"\s+все$|" + _LEAD + r"список (?:всех )?" + _TASK + r"$")
NOTION = re.compile(r"\b(?:ноушен\w*|ношен\w*|нош\w*н|notion)\b|" + _LEAD + r"(?:что|че)?\s*(?:по\s+)?" + _TASK +
                    r"\s+по\s+проектам$|" + _LEAD + r"что (?:еще )?(?:надо|нужно) (?:сделать )?по проектам$")
CAPABILITIES = re.compile(r"\bчто (?:ты )?(?:умеешь|можешь)(?: делать)?\b|\bтвои (?:возможности|команды|функции)\b|"
                          r"\bкакие (?:у тебя )?(?:есть )?(?:команды|функции|возможности)\b|\bсписок (?:твоих )?команд\b|^(?:помощь|справка)$")
AWAKE = re.compile(_LEAD + r"(?:проснись|просыпайся|ты спишь|не спи)$")

AWAKE_REPLY = "Я не сплю, сэр. Слушаю."

# Extra grammar phrases (the Vosk grammar recognizer only knows what it is given).
PHRASES = ["утренний брифинг", "брифинг", "утренняя сводка", "что ещё осталось", "чё ещё осталось", "что осталось",
           "что ещё надо сделать", "перескажи все задачи", "расскажи все задачи", "задачи все перескажи", "все задачи",
           "перечисли все задачи", "задачи по проектам", "что по проектам в ноушене", "что ты умеешь", "что ты можешь",
           "какие у тебя команды", "проснись"]

SERVER_TEXT = {
    "briefing": "Утренний брифинг: коротко календарь, задачи, питание и проекты на сегодня.",
    "left": "Что мне ещё осталось сделать сегодня? Перечисли оставшиеся задачи с временем, если оно задано, "
            "и коротко, что открыто по проектам в Notion.",
    "all": "Перечисли все мои задачи на сегодня и просроченные. У каждой назови время, если оно задано. "
           "Ничего не пропускай, говори коротко.",
    "notion": "Что ещё нужно сделать по проектам в Notion? По каждому проекту: статус и открытые подзадачи.",
}


def intent(text: str) -> Optional[dict]:
    t = VOCAB.norm(text)
    if not t:
        return None
    if AWAKE.search(t):
        return {"name": "awake", "action": "awake"}
    if CAPABILITIES.search(t):
        return {"name": "capabilities", "action": "capabilities"}
    if _MUTATE.search(t):
        return None
    for mode, rx in (("notion", NOTION), ("briefing", BRIEFING), ("all", ALL), ("left", LEFT)):
        if rx.search(t):
            return {"name": "tasks_" + mode, "action": "tasks", "mode": mode}
    return None


# ------------------------------------------------------------------ answers from the snapshot
def _when(value, now: _dt.datetime) -> str:
    """«в 15:30», «завтра в 9:00», «до 10 ноября» from an ISO time; '' when there is none."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if d.tzinfo is not None:
        d = d.astimezone(now.tzinfo) if now.tzinfo else d.astimezone().replace(tzinfo=None)
    has_time = "T" in value and (d.hour or d.minute)
    day = (d.date() - now.date()).days
    at = " в %d:%02d" % (d.hour, d.minute) if has_time else ""
    if day == 0:
        return at.strip()
    if day == 1:
        return ("завтра" + at).strip()
    if day < 0:
        return "просрочена"
    return ("%d %s" % (d.day, _MONTHS[d.month - 1]) + at).strip()


_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _tasks(cache: dict) -> Optional[List[dict]]:
    v = cache.get("tasks")
    if not isinstance(v, list):
        return None
    return [x for x in v if isinstance(x, dict) and isinstance(x.get("title"), str) and x["title"].strip()]


def _task_line(t: dict, now: _dt.datetime) -> str:
    when = _when(t.get("due_iso") or t.get("due"), now)
    if t.get("overdue") and when != "просрочена":
        when = (when + ", просрочена").strip(", ")
    return t["title"].strip().rstrip(".") + (" — " + when if when else "")


def speak_tasks(cache: dict, now: _dt.datetime, only_open: bool) -> Optional[str]:
    tasks = _tasks(cache)
    if tasks is None:
        return None
    if only_open:
        tasks = [t for t in tasks if not t.get("done")]
    if not tasks:
        return "Задач на сегодня не осталось, сэр." if only_open else "Задач на сегодня нет, сэр."
    n = len(tasks)
    head = ("Осталось " if only_open else "Всего ") + JT.num_ru(n, "f") + " " + JT.plural(n, "задача", "задачи", "задач") + ", сэр. "
    return head + ". ".join(_task_line(t, now) for t in tasks) + "."


def _notion_items(cache: dict) -> Optional[List[dict]]:
    v = cache.get("notion_tasks")
    if not isinstance(v, list):
        return None
    return [x for x in v if isinstance(x, dict) and isinstance(x.get("project"), str) and x["project"].strip()]


def speak_notion(cache: dict) -> Optional[str]:
    items = _notion_items(cache)
    if items:
        parts = []
        for it in items:
            line = it["project"].strip().rstrip(".")
            if isinstance(it.get("status"), str) and it["status"].strip():
                line += ", " + it["status"].strip().lower()
            subs = [s.strip().rstrip(".") for s in (it.get("open_subtasks") or []) if isinstance(s, str) and s.strip()]
            line += (": осталось " + ", ".join(subs)) if subs else ""
            parts.append(line)
        return "По проектам в Notion, сэр. " + ". ".join(parts) + "."
    text = cache.get("notion")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def answer(mode: str, cache: Optional[dict], fresh: bool, now: Optional[_dt.datetime] = None, stamp: str = "") -> Tuple[Optional[str], str]:
    """(local reply or None, server request text). Local only from a fresh same-day snapshot.

    ``stamp`` («Данные на двенадцать ноль пять.») is put in front, after «Утренний брифинг» for a briefing.
    """
    reply, server = _answer(mode, cache, fresh, now or _dt.datetime.now().astimezone())
    if reply and stamp:
        head = "Утренний брифинг, сэр. "
        reply = head + stamp + " " + reply[len(head):] if reply.startswith(head) else stamp + " " + reply
    return reply, server


def _answer(mode: str, cache: Optional[dict], fresh: bool, now: _dt.datetime) -> Tuple[Optional[str], str]:
    server = SERVER_TEXT[mode]
    if not cache or not fresh:
        return None, server
    if mode == "all":
        return speak_tasks(cache, now, only_open=False), server
    if mode == "notion":
        return speak_notion(cache), server
    if mode == "left":
        tasks = speak_tasks(cache, now, only_open=True)
        today = cache.get("today") if isinstance(cache.get("today"), str) and cache["today"].strip() else None
        base = tasks or today
        if base is None:
            return None, server
        notion = speak_notion(cache)
        return base + (" " + notion if notion else ""), server
    if mode == "briefing":
        text = cache.get("text") if isinstance(cache.get("text"), str) else ""
        text = re.sub(r"^(?:По данным|Данные) на[^.!?]+[.!?]\s*", "", text.strip(), flags=re.I)
        if not text:
            return None, server
        notion = cache.get("notion") if isinstance(cache.get("notion"), str) and cache["notion"].strip() else ""
        return "Утренний брифинг, сэр. " + text + (" " + notion.strip() if notion else ""), server
    return None, server
