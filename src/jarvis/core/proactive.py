"""Pure proactive rules: defaults, DND phrases, ISO/HH:MM parsing, quiet hours and priority wake.

The persistent queue that uses them is jarvis.adapters.proactive.
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Mapping

DEFAULTS: dict[str, Any] = {
    "proactive_enabled": True, "proactive_quiet_start": "23:00", "proactive_quiet_end": "08:00",
    "proactive_min_interval_s": 120, "proactive_tick_s": 5, "proactive_max_chars": 4000,
    "proactive_training_enabled": False, "proactive_training_time": "12:00", "proactive_training_weekdays": [],
    "proactive_calendar_enabled": True, "proactive_calendar_lead_min": 15, "proactive_cache_max_age_h": 3,
    "proactive_protein_enabled": False, "proactive_protein_time": "18:00", "proactive_protein_expire_time": "22:00",
    "proactive_protein_left_g": 60, "morning_briefing_enabled": False, "morning_start": "07:00", "morning_end": "12:00",
    "morning_idle_s": 14400, "morning_retry_s": 120, "morning_max_attempts": 3, "priority_wake_min_conf": .85, "timezone": "",
}
PHRASES = ["не беспокоить", "режим тишины", "включи режим тишины", "можно беспокоить", "выключи режим тишины"]
REPLIES = ["Не беспокою, сэр.", "Уведомления включены, сэр.", "Через пятнадцать минут тренировка, сэр.",
           "Сэр, до нормы белка осталось больше шестидесяти граммов. Не забудьте про ужин."]
STRESS = {w.replace("+", ""): w for w in ["б+ольше", "ч+ерез", "беспок+ою", "уведомл+ения", "включен+ы", "тренир+овка", "пятн+адцать",
                                         "шест+идесяти", "гр+аммов", "заб+удьте", "+ужин", "начн+ется", "соб+ытие"]}
WAKE_NAMES = {"джарвис", "жарвис", "джервис", "дарвис", "гарвис", "джарви", "джави", "jarvis"}


def intent(text: str) -> dict[str, Any] | None:
    t = " ".join(re.findall(r"\w+", text.lower().replace("ё", "е")))
    if t in PHRASES: return {"name": "dnd_on" if t in PHRASES[:3] else "dnd_off", "action": "proactive_dnd", "enabled": t in PHRASES[:3]}
    return None


def parse_iso(value: Any) -> float:
    """Epoch of an ISO timestamp that carries its own zone."""
    if not isinstance(value, str): raise ValueError("ISO_expected")
    d = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None: raise ValueError("ISO_timezone_required")
    return d.timestamp()


def hm(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value): raise ValueError("invalid_hhmm")
    h, m = map(int, value.split(":")); return h * 60 + m


def wall(day: datetime.date, value: str) -> float:
    # Naive local time .timestamp() uses historical Windows DST, unlike today's fixed UTC offset.
    h, m = map(int, value.split(":"))
    return datetime.datetime.combine(day, datetime.time(h, m)).timestamp()


def quiet(cfg: Mapping[str, Any], epoch: float) -> bool:
    n = datetime.datetime.fromtimestamp(epoch); t = n.hour * 60 + n.minute
    a = hm(cfg.get("proactive_quiet_start", "23:00")); b = hm(cfg.get("proactive_quiet_end", "08:00"))
    return a <= t < b if a < b else (t >= a or t < b) if a > b else False


def priority_candidate(text: str, confidence: float, speaker_text: str, cfg: Mapping[str, Any]) -> bool:
    """Require an actual leading wake name, not just a grammar hallucination or TTS echo."""
    words = re.findall(r"\w+", text.lower().replace("ё", "е")); said = re.findall(r"\w+", speaker_text.lower().replace("ё", "е"))
    wake = next((i for i, w in enumerate(words[:3]) if w in WAKE_NAMES), None)
    if wake is None or confidence < float(cfg.get("priority_wake_min_conf", .85)): return False
    if any(w in WAKE_NAMES for w in said): return False
    return wake == 0 or all(w in ("эй", "хей", "хэй", "слушай", "ну") for w in words[:wake])
