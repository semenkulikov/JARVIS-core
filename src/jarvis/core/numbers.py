"""Russian spoken numbers and durations: «двадцать пять», «полтора часа», «пять минут тридцать секунд»."""
from __future__ import annotations

import re
from jarvis.core.fold import fold

NUM: dict[str, float] = {'ноль':0,'один':1,'одна':1,'одну':1,'два':2,'две':2,'три':3,'четыре':4,'пять':5,'шесть':6,'семь':7,'восемь':8,'девять':9,'десять':10,'одиннадцать':11,'двенадцать':12,'тринадцать':13,'четырнадцать':14,'пятнадцать':15,'шестнадцать':16,'семнадцать':17,'восемнадцать':18,'девятнадцать':19,'двадцать':20,'тридцать':30,'сорок':40,'пятьдесят':50,'шестьдесят':60,'семьдесят':70,'восемьдесят':80,'девяносто':90,'сто':100,'двести':200,'триста':300,'четыреста':400,'пятьсот':500,'шестьсот':600,'семьсот':700,'восемьсот':800,'девятьсот':900,'полтора':1.5,'полторы':1.5}


def norm(t: str) -> str:
    return " ".join(re.sub(r"[^\w\s,.-]", " ", fold(t)).split())


def number(t: str) -> float | None:
    """Digits or a sum of number words («сто двадцать пять»); None when anything else is in the way."""
    t = norm(t).strip(" ,.")
    if re.fullmatch(r"\d+(?:[.,]\d+)?", t): return float(t.replace(",", "."))
    ws = t.split()
    return sum(NUM[w] for w in ws) if ws and all(w in NUM for w in ws) else None


def duration(t: str) -> int | None:
    """Seconds in a spoken span; a bare number means minutes; negative spans are refused."""
    t = norm(t)
    if re.search(r"минус|[-−]\s*\d", t): return None
    if "полчаса" in t: return 1800
    total = 0.0; found = False
    for m in re.finditer(r"((?:\d+(?:[.,]\d+)?|[а-я]+)(?:\s+[а-я]+)*?)\s+(секунд\w*|минут\w*|час\w*)\b", t):
        raw = m[1].split(); vals: list[str] = []
        for w in reversed(raw):
            if number(w) is None: break
            vals.insert(0, w)
        n = number(" ".join(vals))
        if n is None and m[2] in ("минуту", "секунду", "час"): n = 1
        if n is not None: total += n * (1 if m[2].startswith("секунд") else 60 if m[2].startswith("минут") else 3600); found = True
    if not found:
        # Single unit without a preceding number, or bare duration defaults to minutes.
        if re.search(r"\b(?:минуту|секунду|час)\b", t): return 1 if "секунду" in t else 3600 if re.search(r"\bчас\b", t) else 60
        bare = number(t)
        return int(bare * 60) if bare is not None and bare > 0 else None
    return int(total) if total > 0 else None
