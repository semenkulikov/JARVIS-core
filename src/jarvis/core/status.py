"""Status snapshot policy: how old data may be spoken, and which sentence answers a field.

The snapshot is the JSON the user's server writes to ``cache/status.json``; reading the file is
the adapter's job (:mod:`jarvis.adapters.status_cache`).
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Mapping

from jarvis.core import text as JT

Snapshot = Mapping[str, Any]

CACHE_HINTS = {
    "food": r"питани|ккал|килокалор|белк|съеден|калори",
    "today": r"календар|тодоист|задач|встреч|сегодня|тренировк",
    "deploy": r"проект|деплой|коммит|репозитор|гитхаб|сайт",
}


FUTURE_SKEW_MIN = 15.0  # snapshots stamped up to this far ahead still count as fresh


def cache_age_policy(updated: str, cfg: Mapping[str, Any], now: datetime.datetime | None = None) -> tuple[str, float]:
    """("fresh" | "stale" | "old", age in hours); data from another day is always old."""
    now = now or datetime.datetime.now().astimezone()
    dt = datetime.datetime.fromisoformat(updated)
    if dt.tzinfo is None: dt = dt.astimezone()
    local_dt = dt.astimezone(now.tzinfo)
    age = (now - dt).total_seconds() / 3600
    skew_h = float(cfg.get("cache_future_skew_min", FUTURE_SKEW_MIN)) / 60
    if -skew_h <= age < 0: age = 0.0  # the writer's clock runs a little ahead: treat it as just written
    if age < 0 or local_dt.date() != now.date(): return "old", age
    fresh_h = float(cfg.get("cache_max_age_h", 2.5))
    stale_h = max(fresh_h, float(cfg.get("cache_stale_read_max_age_h", 3)))
    if age < fresh_h: return "fresh", age
    return ("stale" if age <= stale_h else "old"), age


def spoken_time(updated: str) -> str:
    """«тринадцать тридцать» for the snapshot time in the local zone."""
    dt = datetime.datetime.fromisoformat(updated).astimezone()
    return JT.time_words(dt.hour, dt.minute)


def derive_field(data: Snapshot, field: str) -> tuple[str | None, str | None]:
    """The field itself, or the summary sentences that mention it; (text, "field" | "derived")."""
    v = data.get(field)
    if isinstance(v, (list, dict)): v = " ".join(str(x) for x in (v.values() if isinstance(v, dict) else v))
    if v: return str(v), "field"
    sents = re.split(r"(?<=[.!?])\s+", data.get("text", ""))
    hit = [x for x in sents[1:] if re.search(CACHE_HINTS.get(field, "$^"), x, re.I)]
    return (" ".join(hit), "derived") if hit else (None, None)


def status_answer(data: Snapshot, field: str | None, cfg: Mapping[str, Any]) -> tuple[str, str, float]:
    """(policy, spoken text with its time stamp, age h); policy "missing" when there is nothing to say."""
    decision, age = cache_age_policy(data["updated"], cfg)
    body = data.get(field or "text")
    if field and not body: body = derive_field(data, field)[0]
    if not isinstance(body, str) or not body.strip(): return "missing", "", age
    body = re.sub(r"^(?:По данным|Данные) на[^.!?]+[.!?]\s*", "", body.strip(), flags=re.I)
    return decision, "По данным на " + spoken_time(data["updated"]) + ", сэр. " + body, age
