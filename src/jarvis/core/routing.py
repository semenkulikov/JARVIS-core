"""Routing: which local action a phrase means, and whether a transcript is worth acting on."""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Callable

import jarvis_commands as QUICK
from jarvis.core import gate as GATE
import jarvis_proactive as PROACTIVE
import jarvis_sleep as SLEEP
from jarvis.core.fuzzy import fuzzy_alias
from jarvis.core import tasks as TASKS
from jarvis.core import vocab as VOCAB
from jarvis.core.matching import filler_only, incomplete_fragment, natural_status_alias, norm_phrase, tok_match
from jarvis.core.state import ListenerState

Config = dict[str, Any]
Alias = dict[str, Any]
log = logging.getLogger("jarvis")

# Actions that only read data: safe to take from the grammar recognizer or a low-confidence follow-up.
READ_ONLY_ACTIONS = ("status", "cache_field", "time", "workout", "tasks", "capabilities")


def match_alias(text: str, cfg: Config) -> Alias | None:
    """The local action for a phrase, or None for the server. Order matters: specific intents first."""
    secs = SLEEP.parse(text)
    if secs: return {"name": "jarvis_sleep", "action": "jarvis_sleep", "seconds": secs}
    proactive = PROACTIVE.intent(text)
    if proactive: return proactive
    task = TASKS.intent(text)
    if task: return task
    toks = norm_phrase(text)
    if not toks: return None
    quick = QUICK.match(text,cfg)
    if quick: return quick
    # Alarm cancellation is NOT the bare stop-speech alias "отмена".
    if re.search(r"будильник", " ".join(toks)):
        return {"name":"alarm_request", "action":"webhook", "target":text}
    # A cached today snapshot cannot answer a date-specific question about another day.
    joined = " ".join(toks)
    if re.search(r"план|задач|статус|отчет|встреч|календар|питан|калори|белк",joined) and re.search(r"\b(?:завтра|послезавтра|вчера|позавчера|недел\w*|месяц\w*|январ\w*|феврал\w*|март\w*|апрел\w*|ма[йяе]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)\b",joined):
        return {"name":"dated_query", "action":"webhook", "target":text}
    natural = natural_status_alias(text)
    if natural: return natural
    fuzzy = fuzzy_alias(text, cfg)
    if fuzzy: return fuzzy
    best: Alias | None = None; bscore = 0
    for al in cfg.get("aliases") or []:
        if al.get("action") == "status": continue  # handled by semantic intent above
        for ph in al.get("phrases", []):
            pt = norm_phrase(ph)
            if not pt: continue
            if al.get("action") == "stop":
                ct = [t for t in toks if t not in ("сэр", "пожалуйста", "ну")]
                if ct != pt: continue
                score = 100 + len(pt)
                if score > bscore: best, bscore = al, score
                continue
            if al.get("action") == "smalltalk":
                ct = [t for t in toks if t not in ("сэр", "пожалуйста", "ну", "э", "эм")]
                if len(ct) != len(pt): continue
                if ct == pt: score = 100 + len(pt)
                elif all(tok_match(a, b) or (min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75) for a, b in zip(ct, pt, strict=True)): score = 20 + len(pt)
                else: continue
                if score > bscore: best, bscore = al, score
                continue
            if toks == pt: score = 100 + len(pt)
            elif len(toks) <= len(pt) + int(al.get("extra_words", 2)) and all(any(tok_match(p, t) for t in toks) for p in pt):
                score = 10 + len(pt)
            else: continue
            if score > bscore: best, bscore = al, score
    if best: return best
    return fuzzy_alias(text, cfg)


def grammar_phrases(cfg: Config) -> list[str]:
    """Phrases for the narrow command recognizer that runs next to the free one."""
    ph: list[str] = []
    for al in cfg.get("aliases") or []:
        for p in al.get("phrases", []):
            p = " ".join(norm_phrase(p))
            if p and al.get("action") not in ("timer", "open_project"): ph.append(p)
    ph += ["расскажи статус по задачам", "что там по задачам", "что там статус по задачам", "статус моих задач", "какие у меня задачи", "что по делам", "что у меня на сегодня", "дай отчет по задачам", "статус питания", "статус по проектам"]
    ph += QUICK.PHRASES + PROACTIVE.PHRASES
    ph += TASKS.PHRASES
    return sorted({VOCAB.vosk_spelling(p) for p in ph if p}) + ["[unk]"]


class Router:
    """Decides on one transcript of the current turn; records a silent drop in the listener state."""

    def __init__(self, state: ListenerState, shutdown_pending: Callable[[], bool] = lambda: False) -> None:
        self.state = state
        self.shutdown_pending = shutdown_pending

    def drop(self, reason: str, text: str) -> tuple[str, bool]:
        """Garbled / background speech: log it and stay silent."""
        self.state.dropped = True
        log.info("dropped silently (%s): %r", reason, text)
        return "", False

    def followup_rescue(self, text: str, gtext: str, cfg: Config) -> str:
        """Low-confidence follow-up: accept the grammar reading of a read-only question when the free text agrees on a content word."""
        ga = match_alias(gtext, cfg) if gtext else None
        if not (text and ga and ga.get("action") in READ_ONLY_ACTIONS): return ""
        free = [t for t in norm_phrase(text) if len(t) >= 4]
        gram = [t for t in norm_phrase(gtext) if len(t) >= 4]
        return gtext if any(tok_match(a, b) for a in free for b in gram) else ""

    def choose(self, text: str, conf: float, gtext: str, cfg: Config, followup: bool = False) -> tuple[str, bool]:
        """The phrase to act on and whether it is understood; garbage is dropped silently."""
        self.state.dropped = False
        if text and filler_only(text) and not self.shutdown_pending():
            log.info("filler-only/echo transcript ignored: %r", text); return "", False
        al = match_alias(text, cfg) if text else None
        ga = match_alias(gtext, cfg) if gtext else None
        if al:
            if al.get("action") in READ_ONLY_ACTIONS and conf<float(cfg.get("min_conf",0.55)) and not (gtext and ga):
                log.info("local intent rejected: low ASR confidence %.2f",conf); return text,False
            if al.get("action") in ("quick2","proactive_dnd","jarvis_sleep") and conf<float(cfg.get("min_conf",0.55)):
                log.info("quick command rejected: low ASR confidence %.2f",conf); return text, False
            if al.get("_fuzzy") and conf < float(cfg.get("min_conf",0.55)):
                log.info("fuzzy intent rejected: low ASR confidence %.2f",conf); return text, False
            exact = any(norm_phrase(text) == norm_phrase(p) for p in al.get("phrases", []))
            if al.get("action") == "smalltalk" and not exact and conf < 0.8 and ga and ga.get("action") == "smalltalk":
                log.info("grammar smalltalk wins over fuzzy guess: %r (free %r conf %.2f)", gtext, text, conf); return gtext, True
            return text, True
        if not followup and cfg.get("grammar_command_rescue", True) and QUICK.grammar_rescue(text, gtext, ga, float(cfg.get("grammar_rescue_min_ratio", 0.6))):
            log.info("grammar command wins: %r (free %r conf %.2f)", gtext, text, conf); return gtext, True
        if incomplete_fragment(text):
            return self.drop("fragment", text)
        safe_grammar = ga and ga.get("action") in READ_ONLY_ACTIONS + ("smalltalk", "stop")
        if gtext and safe_grammar and not followup and (not text or conf < 0.8):
            log.info("grammar hint wins: %r (free %r conf %.2f)", gtext, text, conf); return gtext, True
        if not text: return "", False
        meta = self.state.last_capture or {}
        words = meta.get("words") or [{"word": w, "conf": conf} for w in norm_phrase(text)]
        reason = GATE.reject_reason(words, cfg, followup=followup, hit_max=bool(meta.get("hit_max")))
        if reason: return self.drop(reason, text)
        return text, True
