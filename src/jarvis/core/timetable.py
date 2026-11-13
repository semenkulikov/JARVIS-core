"""Fixed-time schedule (config section ``schedule``): when each entry is due. The workout answer is jarvis.core.schedule.

Pure rules only; the persistent queue that speaks the entries is jarvis.adapters.proactive.
Times are local wall-clock times of the operating system's zone (DST-aware, see
:func:`jarvis.core.proactive.wall`). A briefing entry is tied to the *scheduled* time of the entry
it follows (``after`` + ``delay_min``), not to the moment the user actually woke up.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from jarvis.core.proactive import hm, wall

log = logging.getLogger("jarvis")

KINDS = ("say", "briefing")
BRIEFING_STYLE = "plan_and_recommendations"
WEEKDAYS_RU = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
GRACE_MIN = 2.0          # a tick or two late is still «on time»; later means Jarvis was off or the laptop slept
SAY_LATE_MIN = 10.0      # a say entry without late_skip_min is dropped this long after its time
FALLBACK_PHRASE = "Сэр, сервер не прислал брифинг."
NO_SNAPSHOT_PHRASE = "Свежих данных тоже нет."

DEFAULTS: dict[str, Any] = {
    "schedule": [
        {"id": "wake_up", "time": "08:00", "kind": "say", "volume": 100, "override_quiet": True, "late_skip_min": 10,
         "say": ["Солнце светит, лыжники катаются, доллар падает, а ты ещё валяешься! Подъём, ленивый сэр!"]},
        {"id": "morning_briefing", "kind": "briefing", "after": "wake_up", "delay_min": 60, "prefetch_min": 10,
         "catch_up_until": "12:00"},
        {"id": "bedtime", "time": "22:00", "kind": "say", "say": ["Сэр, пора ложиться.", "Сэр, отбой. Завтра рано вставать."],
         "repeat_after_min": 15, "max_repeats": 1},
    ],
}


@dataclass(frozen=True)
class Entry:
    """One validated schedule entry; ``minute`` is the local wall-clock minute of the day (may pass 24:00)."""

    id: str
    kind: str
    minute: int
    say: tuple[str, ...] = ()
    volume: int | None = None
    override_quiet: bool = False
    late_skip_min: float | None = None
    prefetch_min: float = 0.0
    catch_up_until: str | None = None
    repeat_after_min: float = 0.0
    max_repeats: int = 0
    weekdays: tuple[int, ...] | None = None
    style: str = BRIEFING_STYLE

    def runs_on(self, day: datetime.date) -> bool:
        return self.weekdays is None or day.weekday() in self.weekdays

    def at(self, day: datetime.date, n: int = 0) -> float:
        """Epoch of the n-th sounding (0 = the entry itself, then the repeats) on ``day``."""
        base = wall(day + datetime.timedelta(days=self.minute // 1440), "%02d:%02d" % divmod(self.minute % 1440, 60))
        return base + n * self.repeat_after_min * 60

    def until(self, day: datetime.date, n: int = 0) -> float:
        """Epoch after which the n-th sounding is dropped for the day."""
        due = self.at(day, n)
        if self.catch_up_until: return max(due, wall(day, self.catch_up_until))
        late = self.late_skip_min if self.late_skip_min is not None else SAY_LATE_MIN
        if self.repeat_after_min and n < self.max_repeats: late = min(late, self.repeat_after_min)
        return due + late * 60

    def key(self, day: datetime.date, n: int = 0) -> str:
        return "schedule:%s:%s:%d" % (self.id, day.isoformat(), n)


def _num(raw: Mapping[str, Any], name: str, default: float, low: float = 0.0) -> float:
    v = raw.get(name, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < low: raise ValueError(name)
    return float(v)


def parse(cfg: Mapping[str, Any]) -> list[Entry]:
    """Valid entries of ``cfg["schedule"]``; a broken entry is logged and skipped, never the whole section."""
    raw = cfg.get("schedule") or []
    if not isinstance(raw, list): log.warning("schedule: a list expected"); return []
    times: dict[str, int] = {}; out: list[Entry] = []
    pending = [r for r in raw if isinstance(r, dict) and r.get("enabled", True)]
    for _ in range(len(pending) + 1):  # entries may follow entries listed after them
        left = []
        for r in pending:
            try:
                e = _entry(r, times)
            except LookupError: left.append(r); continue
            except (ValueError, TypeError) as err:
                log.warning("schedule entry %r skipped: bad %s", r.get("id"), err); continue
            times[e.id] = e.minute; out.append(e)
        if len(left) == len(pending): break
        pending = left
    for r in pending: log.warning("schedule entry %r skipped: unknown after %r", r.get("id"), r.get("after"))
    return out


def _entry(r: Mapping[str, Any], times: Mapping[str, int]) -> Entry:
    eid = r.get("id")
    if not isinstance(eid, str) or not eid: raise ValueError("id")
    kind = r.get("kind", "say")
    if kind not in KINDS: raise ValueError("kind")
    if r.get("after"):
        if r["after"] not in times: raise LookupError(r["after"])
        minute = times[r["after"]] + int(_num(r, "delay_min", 0))
    else: minute = hm(r.get("time"))
    say = r.get("say", [])
    say = (say,) if isinstance(say, str) else tuple(str(x) for x in say if str(x).strip())
    if kind == "say" and not say: raise ValueError("say")
    volume = r.get("volume")
    if volume is not None and (isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 100): raise ValueError("volume")
    days = r.get("weekdays")
    if days is not None and (not isinstance(days, list) or any(isinstance(d, bool) or d not in range(7) for d in days)): raise ValueError("weekdays")
    until = r.get("catch_up_until")
    if until is not None: hm(until)
    late = r.get("late_skip_min")
    return Entry(eid, kind, minute, say, None if volume is None else int(volume), bool(r.get("override_quiet", False)),
                 None if late is None else _num(r, "late_skip_min", 0), _num(r, "prefetch_min", 0), until,
                 _num(r, "repeat_after_min", 0), int(_num(r, "max_repeats", 0)) if r.get("repeat_after_min") else 0,
                 None if days is None else tuple(days), str(r.get("style") or BRIEFING_STYLE))


def day_fields(now: float, cfg: Mapping[str, Any]) -> dict[str, str]:
    """``local_time`` (ISO with offset), ``weekday`` (Russian), ``local_date`` and ``timezone`` for a briefing request."""
    n = datetime.datetime.fromtimestamp(now).astimezone()
    return {"local_time": n.isoformat(timespec="seconds"), "weekday": WEEKDAYS_RU[n.weekday()],
            "local_date": n.date().isoformat(), "timezone": str(cfg.get("timezone") or n.tzname())}


def phrases(entries: Iterable[Entry]) -> list[str]:
    """Fixed phrases of the say entries, for the start-up synthesis cache."""
    return [p for e in entries if e.kind == "say" for p in e.say] + [FALLBACK_PHRASE + " " + NO_SNAPSHOT_PHRASE]
