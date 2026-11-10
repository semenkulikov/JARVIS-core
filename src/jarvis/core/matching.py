"""Phrase normalisation and small text predicates shared by routing, capture and replies."""
from __future__ import annotations

import difflib
import re
from typing import Any
from jarvis.core.fold import fold

Alias = dict[str, Any]


def norm_phrase(t: str | None) -> list[str]:
    """Lower-case word tokens with «ё» folded to «е» and punctuation dropped."""
    t = fold(t)
    return re.sub(r"[^\w\s]", " ", t).split()


def tok_match(a: str, b: str) -> bool:
    """Same word allowing a different ending or a small recognition slip."""
    if a == b: return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b[:-1]) or b.startswith(a[:-1])): return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def natural_status_alias(text: str) -> Alias | None:
    """Free wording of a status question («что там по делам») mapped to a cached report."""
    t = " ".join(norm_phrase(text))
    t = re.sub(r"^(ну |а )?че\b", r"\1что", t)
    # Keep mutation/instruction requests on their real route.
    if re.search(r"отмет|выполн|заверш|закро[йю]|сделан|галочк|как бы полная|как полная", t): return None
    if re.search(r"\b(добав\w*|созда\w*|удал\w*|постав\w*|отмен\w*|измени\w*|перенес\w*|напомни\w*|открой|объясни|почему|как работает)\b", t): return None
    report = bool(re.search(r"\b(статус\w*|отчет\w*|доклад\w*|сводк\w*|задач\w*)\b|что (?:там |у нас |у меня )?по делам|какие (?:у меня )?дела", t))
    if report and re.search(r"питан|калори|белк|\bед[аеуы]\b", t):
        return {"name": "food", "action": "cache_field", "field": "food"}
    if report and re.search(r"проект|депло|коммит|сайт|гитхаб", t):
        return {"name": "deploy", "action": "cache_field", "field": "deploy"}
    if report and re.search(r"задач|делам|дела\b|на сегодня|сегодняшн", t):
        return {"name": "task_status", "action": "cache_field", "field": "today"}
    if report: return {"name": "status", "action": "status"}
    if re.search(r"^(?:ну |а )?(?:что (?:там )?(?:у меня )?(?:на сегодня|по планам)|какие (?:у меня )?задачи)", t):
        return {"name": "task_status", "action": "cache_field", "field": "today"}
    return None


FILLER_TOKENS = frozenset({"сэр", "ну", "э", "эм", "а", "ага", "угу", "так"})


def filler_only(text: str) -> bool:
    """«ну», «да, сэр» and the like: nothing to act on."""
    toks = norm_phrase(text)
    if not toks: return False
    if all(t in FILLER_TOKENS for t in toks): return True
    return toks in (["да", "сэр"], ["да", "да", "сэр"], ["сэр", "да"])


def incomplete_fragment(text: str) -> bool:
    """A cut-off tail of a sentence («в вашем», «и отметил») that must not be answered."""
    t = " ".join(norm_phrase(text))
    return bool(re.fullmatch(r"(?:в|на|по|с|из|о|об|для|к|у) (?:вашем|твоем|моем|этом|том|вас|меня)|(?:как|что|ну|это|там|ты|и отметил|и отметь)", t))


def pure_wait_filler(text: str) -> bool:
    """A server part that only says «минуту, уточняю» after the listener already acknowledged."""
    t = " ".join(norm_phrase(text))
    t = re.sub(r"\bсэр\b", "", t); t = " ".join(t.split())
    return bool(re.fullmatch(r"(?:(?:одну )?(?:минуту|секунду)(?: (?:уточняю|проверяю|посмотрю))?|(?:сейчас |уже )?(?:посмотрю|уточню|проверю|проверяю|смотрю|уточняю|запрашиваю)(?: (?:данные|календарь|задачи|статус))?|почти готово)", t))


def followup_echo(text: str, spoken: str | None) -> bool:
    """The follow-up transcript repeats a sentence the assistant itself just said."""
    tt = norm_phrase(text)
    if len(tt) < 2: return False
    sentences = re.split(r"[.!?…]+", spoken or "")
    return any(tt == norm_phrase(sent) for sent in sentences) or tt == norm_phrase(spoken)


def corroborated_stop(ph: str, free_text: str) -> bool:
    """The stop grammar's phrase also appears in the free transcript, without a negation."""
    pt = norm_phrase(ph); ft = norm_phrase(free_text)
    if not pt or "[unk]" in free_text or re.search(r"\b(?:не|нет)\b", free_text): return False
    return any(ft[i:i + len(pt)] == pt for i in range(len(ft) - len(pt) + 1))


def stop_candidate(ph: str, conf: float, echo: bool, cfg: dict[str, Any]) -> bool:
    normalized = " ".join(norm_phrase(ph))
    allowed = {" ".join(norm_phrase(p)) for p in cfg.get("stop_phrases", [])}
    return normalized in allowed and conf >= float(cfg.get("bargein_min_conf", 0.60)) and not echo
