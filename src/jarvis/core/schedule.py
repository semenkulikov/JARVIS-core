"""Workout schedule answer: the time now and how long until the next workout."""
from __future__ import annotations

import datetime
from typing import Any, Mapping

from jarvis.core import text as JT

DAYS_ACC = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]


def workout_summary(cfg: Mapping[str, Any], now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now()
    s = f"Сейчас {JT.time_words(now.hour, now.minute)}."
    hh, mm = map(int, cfg["workout_time"].split(":"))
    days = cfg["workout_days"]
    if not days: return "Расписание тренировок ещё не настроено, сэр."
    if now.weekday() in days:
        tw = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < tw:
            m = int((tw - now).total_seconds() // 60); H, M = divmod(m, 60); parts = []
            if H: parts.append(f"{JT.num_ru(H)} {JT.plural(H,'час','часа','часов')}")
            if M or not H: parts.append(f"{JT.num_ru(M, 'f')} {JT.plural(M,'минута','минуты','минут')}")
            return s + " До тренировки " + " ".join(parts) + "."
        if (now - tw).total_seconds() < 5400: return s + " Тренировка идёт прямо сейчас."
    for i in range(1, 8):
        d = (now.weekday() + i) % 7
        if d in days:
            when = "завтра" if i == 1 else ("во " if d == 1 else "в ") + DAYS_ACC[d]
            pre = "Сегодня тренировки нет" if now.weekday() not in days else "Сегодняшняя тренировка уже была"
            return s + f" {pre}, следующая {when} в {JT.time_words(hh, mm)}."
    return s
