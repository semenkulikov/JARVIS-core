"""Jarvis sleep mode phrases: the listener itself goes fully silent for a while.

It never locks the screen, mutes audio or changes any system setting. The persisted end
time lives in jarvis.adapters.sleep_store.
"""
from __future__ import annotations

import re
from typing import Optional

from jarvis.core import numbers as NUMBERS
from jarvis.core import quick as Q
from jarvis.core.fold import fold
from jarvis.core.names import DEFAULT as NAMES
from jarvis.core.names import NameSet

DEFAULT_S = 3600
MIN_S = 60
MAX_S = 12 * 3600

_ENTER = (r"(?:(?:включи|перейди в|уйди в|войди в|переключись в|активируй|в) )?"
          r"(?:спящий режим|режим сна|режим сон)")
_VERB = r"(?:засни|усни|спи|поспи|иди спать|уйди спать|ложись спать)"
SLEEP_RE = re.compile(rf"^(?:{_ENTER}|{_VERB})(?: (?:на|в течение) (?P<dur>.+?))?(?: пожалуйста)?$")
# Bare «режим сна» stays the old desktop sleep command (screen off + lock) from jarvis.core.quick.
LEGACY_BARE = {"режим сна", "режим сон", "включи режим сна", "включи режим сон"}
WAKE_FILE = "wake_up"
WAKE_HINT = "Разбудить: Джарвис, проснись."
DEFAULTS = {"sleep_hint_enabled": True, "sleep_hint_interval_s": 600}


def _norm(text: str, names: NameSet = NAMES) -> str:
    t = fold(text)
    return " ".join(names.strip(re.sub(r"[^\w\s]", " ", t).split()))


def parse(text: str, names: NameSet = NAMES) -> Optional[int]:
    """Seconds of sleep requested by ``text``; None when it is not a sleep command."""
    t = _norm(text, names)
    if t in LEGACY_BARE:
        return None
    m = SLEEP_RE.fullmatch(t)
    if not m:
        return None
    secs = NUMBERS.duration(m["dur"]) if m["dur"] else DEFAULT_S
    return int(min(MAX_S, max(MIN_S, secs or DEFAULT_S)))


def label(secs: int) -> str:
    return Q.duration_label(int(round(secs / 60.0)) * 60 if secs >= 60 else secs)


def enter_phrase(secs: int) -> str:
    """Spoken before going silent, so the owner always hears how long and how to wake Jarvis."""
    return "Ухожу в спящий режим на " + label(secs) + ", сэр. " + WAKE_HINT


def hint_phrase(remaining_s: float) -> str:
    """Answer to a bare «Джарвис» from the owner while asleep."""
    return "Я в спящем режиме ещё " + label(max(60, int(remaining_s))) + ", сэр. " + WAKE_HINT


def is_wake_phrase(text: str, names: NameSet = NAMES) -> bool:
    """«<любое имя> проснись» and its variants (jarvis.core.names)."""
    return " ".join(fold(text).split()) in names.wake_phrases()


def is_hint_word(text: str, names: NameSet = NAMES) -> bool:
    """A bare name while asleep."""
    return " ".join(fold(text).split()) in names.hint_phrases()
