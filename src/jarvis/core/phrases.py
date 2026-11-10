"""Spoken phrase lists: local small talk and varied acknowledgements without repeats."""
from __future__ import annotations

import datetime
import random
from typing import Any, Mapping

import jarvis_commands as QUICK
import jarvis_dialog as DIALOG
import jarvis_proactive as PROACTIVE

# Local conversation: whole short utterances only, never a substring in a request.
SMALLTALK: list[tuple[str, list[str], list[str]]] = [
    ("morning", ["доброе утро", "с добрым утром", "доброго утра"], ["Доброе утро, сэр. Рад вас слышать.", "С добрым утром, сэр. Я к вашим услугам.", "Доброе утро, сэр. Хорошего начала дня."]),
    ("day", ["добрый день", "доброго дня"], ["Добрый день, сэр. Рад вас слышать.", "Доброго дня, сэр. Всегда к вашим услугам."]),
    ("evening", ["добрый вечер", "доброго вечера"], ["Добрый вечер, сэр. Рад вас слышать.", "Добрый вечер, сэр. Надеюсь, день прошёл хорошо."]),
    ("night", ["спокойной ночи", "доброй ночи", "я спать", "иду спать"], ["Спокойной ночи, сэр. Приятных снов.", "Доброй ночи, сэр. Хорошего отдыха."]),
    ("hello", ["привет", "приветик", "здравствуй", "здравствуйте", "здорово", "салют", "хай"], ["Рад вас слышать, сэр.", "Здравствуйте, сэр. Я к вашим услугам.", "{greeting}, сэр. Рад вас слышать."]),
    ("how", ["как дела", "как ты", "как твои дела", "как поживаешь", "как настроение", "как сам"], ["Всё в порядке, сэр. Рад нашей беседе.", "Прекрасно, сэр. Особенно когда вы на связи.", "В рабочем настроении, сэр. А вы как?"]),
    ("thanks", ["спасибо", "благодарю", "спасибочки", "спасибо тебе", "большое спасибо"], ["Всегда пожалуйста, сэр.", "Рад помочь, сэр.", "К вашим услугам, сэр."]),
    ("praise", ["молодец", "умница", "красавчик", "отличная работа", "хорошая работа", "ты лучший"], ["Благодарю, сэр. Стараюсь для вас.", "Приятно слышать, сэр.", "Рад, что вы довольны, сэр."]),
    ("here", ["ты тут", "ты здесь", "ты на месте", "ты на связи", "слышишь меня", "ты меня слышишь"], ["Да, сэр. Я здесь и слушаю.", "На связи, сэр.", "Здесь, сэр. К вашим услугам."]),
    ("identity", ["кто ты", "как тебя зовут", "ты кто"], ["Джарвис, сэр. Ваш голосовой помощник.", "Ваш Джарвис, сэр. Всегда к вашим услугам."]),
    ("bye", ["пока", "до свидания", "до встречи", "увидимся"], ["До встречи, сэр. Я остаюсь на связи.", "Всего доброго, сэр.", "До свидания, сэр. Хорошего {daypart}."]),
    ("okay", ["окей", "хорошо", "ладно", "понятно", "ясно", "все хорошо", "все нормально", "да да да", "да да", "да окей"], ["Хорошо, сэр.", "Понял вас, сэр.", "Как скажете, сэр."]),
    ("done", ["все", "это все", "на этом все", "все спасибо", "пока все", "больше ничего"], ["Хорошо, сэр.", "Как скажете, сэр.", "Понял, сэр. Я на связи."]),
    ("mood", ["у меня все хорошо", "у меня все отлично", "нормально", "все отлично"], ["Рад это слышать, сэр.", "Прекрасно, сэр. Пусть так и продолжается."]),
]
SMALLTALK_ALIASES: list[dict[str, Any]] = [{"name": "chat_" + k, "phrases": ph, "action": "smalltalk", "replies": r, "extra_words": 0}
                                       for k, ph, r in SMALLTALK]
ACK_LIST_KEYS = ("fast_ack", "ack_status", "ack_stop", "ack_command", "ack_free", "ack_wait", "ack_not_understood")


class Picker:
    """Random choice from a configured phrase list, never the same phrase twice in a row per key."""

    def __init__(self, defaults: Mapping[str, Any]) -> None:
        self.defaults = defaults
        self._last: dict[str, str] = {}

    def pick(self, cfg: Mapping[str, Any], key: str) -> str:
        v: Any = cfg.get(key) or self.defaults.get(key)
        if isinstance(v, str): return v
        v = [x for x in v if x] or [""]
        c = [x for x in v if x != self._last.get(key)] or v
        r = random.choice(c); self._last[key] = r; return r


def smalltalk_reply(al: Mapping[str, Any], picker: Picker, now: datetime.datetime | None = None) -> str:
    hour = (now or datetime.datetime.now()).hour
    greeting = "Доброе утро" if 5 <= hour < 12 else "Добрый день" if 12 <= hour < 18 else "Добрый вечер" if 18 <= hour < 23 else "Доброй ночи"
    daypart = "дня" if 5 <= hour < 18 else "вечера" if 18 <= hour < 23 else "отдыха"
    text = picker.pick({al["name"]: al["replies"]}, al["name"])
    return text.format(greeting=greeting, daypart=daypart)


def all_phrases(cfg: dict[str, Any]) -> list[str]:
    """Every fixed phrase the assistant may say, for the start-up synthesis cache."""
    out: list[str] = []
    for k in ACK_LIST_KEYS:
        v = cfg.get(k) or []
        out += [v] if isinstance(v, str) else list(v)
    out += DIALOG.phrase_lists(cfg)
    for al in SMALLTALK_ALIASES:
        for r in al["replies"]:
            if "{" not in r: out.append(r)
            else:
                for greeting in ("Доброе утро", "Добрый день", "Добрый вечер", "Доброй ночи"):
                    for daypart in ("дня", "вечера", "отдыха"):
                        out.append(r.format(greeting=greeting, daypart=daypart))
    out += QUICK.CACHED_REPLIES + PROACTIVE.REPLIES
    return list(dict.fromkeys(out))
