"""Protocols: named multi-step scenarios started by one phrase («протокол спящая красавица»).

Pure part: the ``protocols`` config, phrase matching (with an optional «на шесть часов»), the
aliases that put the phrases into the router and the grammar, and the window grid. The steps
themselves run in jarvis.commands.protocols.
"""
from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from jarvis.core import numbers as NUMBERS
from jarvis.core import sleep as SLEEP
from jarvis.core.matching import norm_phrase, tok_match

log = logging.getLogger("jarvis")

DEFAULTS: dict[str, Any] = {
    "protocols": [
        {"name": "Спящая красавица", "phrases": ["протокол спящая красавица", "протокол спящая царевна"],
         "steps": ["media_pause", "sleep_until_alarm", "cancel_bedtime_repeat"], "reply": "Спокойной ночи, сэр.",
         "summary": "ухожу спать или на созвон: пауза и тишина до будильника"},
        {"name": "Негры пашут", "phrases": ["протокол негры пашут"], "steps": ["launch_workspace", "focus"],
         "reply": "Рабочий режим включён, сэр.", "summary": "начало работы: программы из workspace и фокус"},
        {"name": "Бобик сдох", "phrases": ["протокол бобик сдох"],
         "steps": ["close_all", "minimize_all", "media_pause", "lock"], "reply": "Бобик сдох, сэр.",
         "summary": "конец работы: закрыть все окна, пауза, блокировка"},
        {"name": "Взлом Пентагона", "phrases": ["протокол взлом пентагона"], "steps": ["hacker_windows"], "reply": "Доступ получен, сэр.",
         "summary": "зелёные окна «хакера», закрыть — «отмена протокола»"},
    ],
    "workspace": [],        # programs, folders and URLs «launch» opens: paths, URLs or command lines
    "close_apps": [],       # process names «close_apps» asks to close, e.g. "telegram", "chrome"
    "protocol_hacker_windows": 6,
    # Owner-only additions kept out of git, relative to the Jarvis home (see merge_local).
    "protocols_local_file": "secrets/protocols.local.json",
}
LIST_PHRASES = ("какие протоколы", "какие есть протоколы", "список протоколов", "перечисли протоколы")
CANCEL_PHRASES = ("отмена протокола", "отмени протокол", "отменить протокол", "отбой протокола")
# Steps that change things the owner may not get back: a protocol with them always asks first.
CONFIRM_STEPS = frozenset({"shutdown"})
DEFAULT_REPLY = "Протокол выполнен, сэр."


@dataclass(frozen=True)
class Step:
    name: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class Protocol:
    name: str
    phrases: tuple[str, ...]
    steps: tuple[Step, ...]
    reply: str
    confirm: bool
    summary: str = ""  # one line for the cheat-sheet overlay

    @property
    def needs_confirm(self) -> bool:
        return self.confirm or any(s.name in CONFIRM_STEPS for s in self.steps)

    @property
    def alias_name(self) -> str:
        return "protocol_" + "_".join(norm_phrase(self.name))


def _steps(raw: Any) -> tuple[Step, ...]:
    out = []
    for s in raw if isinstance(raw, list) else []:
        if isinstance(s, str) and s: out.append(Step(s, {}))
        elif isinstance(s, dict) and isinstance(s.get("step"), str): out.append(Step(s["step"], {k: v for k, v in s.items() if k != "step"}))
        else: raise ValueError("step")
    return tuple(out)


def parse(cfg: Mapping[str, Any]) -> list[Protocol]:
    """Valid entries of ``cfg["protocols"]``; a broken one is logged once and skipped."""
    try: key = json.dumps(cfg.get("protocols") or [], ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError): return []
    return list(_parse(key))


@functools.lru_cache(maxsize=8)
def _parse(key: str) -> tuple[Protocol, ...]:
    raw = json.loads(key)
    out: list[Protocol] = []
    for r in raw if isinstance(raw, list) else []:
        try:
            if not isinstance(r, dict) or not r.get("enabled", True): continue
            name = r.get("name"); phrases = r.get("phrases")
            if not isinstance(name, str) or not name.strip(): raise ValueError("name")
            if not isinstance(phrases, list) or not all(isinstance(p, str) and norm_phrase(p) for p in phrases) or not phrases: raise ValueError("phrases")
            steps = _steps(r.get("steps"))
            if not steps: raise ValueError("steps")
            out.append(Protocol(name.strip(), tuple(" ".join(norm_phrase(p)) for p in phrases), steps,
                                str(r.get("reply") or DEFAULT_REPLY), bool(r.get("confirm", False)), str(r.get("summary") or "")))
        except (ValueError, TypeError) as e:
            log.warning("protocol %r skipped: bad %s", r.get("name") if isinstance(r, dict) else r, e)
    return tuple(out)


def merge_local(protocols: Any, local: Any) -> list[Any]:
    """Protocols with the owner's local file applied: ``{"extend": {name: {"steps": [...], "reply": ...}},
    "protocols": [...]}``. Extra steps go after the protocol's own; new protocols are appended.
    The local file is for personal hosts and paths that must never reach the repository."""
    out = [dict(p) if isinstance(p, dict) else p for p in (protocols if isinstance(protocols, list) else [])]
    if not isinstance(local, dict): return out
    raw = local.get("extend"); extend: dict[str, Any] = raw if isinstance(raw, dict) else {}
    for p in out:
        add = extend.get(str(p.get("name"))) if isinstance(p, dict) else None
        if not isinstance(add, dict): continue
        if isinstance(add.get("steps"), list): p["steps"] = list(p.get("steps") or []) + add["steps"]
        if isinstance(add.get("reply"), str): p["reply"] = add["reply"]
    extra = local.get("protocols")
    return out + ([x for x in extra if isinstance(x, dict)] if isinstance(extra, list) else [])


def _same(said: list[str], phrase: list[str]) -> bool:
    return len(said) == len(phrase) and all(tok_match(a, b) for a, b in zip(said, phrase, strict=True))


def match(text: str, protocols: Iterable[Protocol]) -> dict[str, Any] | None:
    """The protocol alias for a phrase: an exact protocol phrase, optionally followed by «на <срок>»."""
    toks = [t for t in norm_phrase(text) if t not in ("пожалуйста", "сэр")]
    if not toks or not tok_match(toks[0], "протокол"): return None
    for p in protocols:
        for ph in p.phrases:
            pt = ph.split()
            if _same(toks[:len(pt)], pt):
                rest = toks[len(pt):]; secs = None
                if rest:
                    if rest[0] not in ("на", "в") or len(rest) < 2: continue
                    secs = NUMBERS.duration(" ".join(rest[1:]))
                    if not secs: continue
                    secs = int(min(SLEEP.MAX_S, max(SLEEP.MIN_S, secs)))
                return {"name": p.alias_name, "action": "protocol", "protocol": p.name, "seconds": secs}
    return None


def intent(text: str, cfg: Mapping[str, Any], protocols: Iterable[Protocol] | None = None) -> dict[str, Any] | None:
    """Protocol, «какие протоколы» or «отмена протокола»; None for anything else."""
    joined = " ".join(norm_phrase(text))
    if joined in LIST_PHRASES: return {"name": "protocol_list", "action": "protocol_list"}
    if joined in CANCEL_PHRASES: return {"name": "protocol_cancel", "action": "protocol_cancel"}
    return match(text, parse(cfg) if protocols is None else protocols)


def aliases(cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Router and grammar entries for every protocol plus the list and cancel phrases."""
    out: list[dict[str, Any]] = [{"name": p.alias_name, "action": "protocol", "protocol": p.name, "phrases": list(p.phrases), "extra_words": 0}
                                 for p in parse(cfg)]
    out.append({"name": "protocol_list", "action": "protocol_list", "phrases": list(LIST_PHRASES), "extra_words": 0})
    out.append({"name": "protocol_cancel", "action": "protocol_cancel", "phrases": list(CANCEL_PHRASES), "extra_words": 0})
    return out


def phrases(cfg: Mapping[str, Any]) -> list[str]:
    """Every protocol phrase, for the vocabulary check of the Vosk model."""
    return [ph for p in parse(cfg) for ph in p.phrases] + list(LIST_PHRASES) + list(CANCEL_PHRASES)


def grid(n: int, width: int, height: int, top: int = 0) -> list[tuple[int, int, int, int]]:
    """``n`` window rectangles (x, y, w, h) tiling the screen in up to three columns."""
    if n <= 0 or width <= 0 or height <= 0: return []
    cols = min(3, n); rows = -(-n // cols); w = width // cols; h = (height - top) // rows
    return [((i % cols) * w, top + (i // cols) * h, w, h) for i in range(n)]
