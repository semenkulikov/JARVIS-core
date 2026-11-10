"""Conservative fuzzy match of short read-only questions (status, time, workout) to known aliases."""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Callable, Mapping

log = logging.getLogger("jarvis")
_MUTATION = re.compile(r"\b(?:добав\w*|созда\w*|удал\w*|постав\w*|отмен\w*|измени\w*|перенес\w*|отмет\w*|выполн\w*|закро\w*|заверш\w*"
                       r"|напомни\w*|открой|запиши|почему|объясни)\b")
_STOP = {"у", "меня", "мне", "на", "по", "там", "ну", "а", "что", "какие", "как", "сэр", "пожалуйста", "сегодня"}
READ_ONLY = ("status", "cache_field", "time", "workout")


def norm(text: str | None) -> str:
    words = re.sub(r"[^\w\s]", " ", (text or "").lower().replace("ё", "е")).split()
    words = ["что" if w in ("че", "чо") else w for w in words]
    return " ".join(w for w in words if w not in ("ну", "сэр", "пожалуйста"))


def _scorer() -> tuple[Callable[[str, str], float], str]:
    try:
        from rapidfuzz.fuzz import ratio, token_sort_ratio

        def fast(a: str, b: str) -> float: return float(max(ratio(a, b), token_sort_ratio(a, b)))
        return fast, "rapidfuzz"
    except ImportError:
        def slow(a: str, b: str) -> float: return 100 * difflib.SequenceMatcher(None, a, b).ratio()
        return slow, "difflib-fallback"


def fuzzy_alias(text: str, cfg: Mapping[str, Any]) -> dict[str, Any] | None:
    """The read-only alias the phrase is clearly closest to, or None (mutating phrases never match)."""
    if not cfg.get("intent_fuzzy_enabled", True): return None
    text = norm(text)
    words = text.split()
    if not words or len(words) > int(cfg.get("intent_max_words", 8)) or _MUTATION.search(text): return None
    anchors = [w for w in words if w not in _STOP]
    if not anchors: return None
    score, engine = _scorer()
    ranked: dict[tuple[Any, Any], tuple[float, dict[str, Any]]] = {}
    for alias in cfg.get("aliases", []):
        if alias.get("action") not in READ_ONLY: continue
        intent = (alias.get("action"), alias.get("field"))
        for phrase in alias.get("phrases", []):
            phrase = norm(phrase); pw = phrase.split()
            # Require a meaningful shared/similar content word; no token-set subset match.
            pa = [w for w in pw if w not in _STOP]
            if not pa or not any(score(a, b) >= 82 for a in anchors for b in pa): continue
            value = score(text, phrase)
            if value > ranked.get(intent, (0.0, {}))[0]: ranked[intent] = (value, alias)
    ranks = sorted(ranked.values(), key=lambda x: x[0], reverse=True)
    threshold = float(cfg.get("intent_fuzzy_threshold", 88))
    margin = float(cfg.get("intent_fuzzy_margin", 7))
    if not ranks or ranks[0][0] < threshold or (len(ranks) > 1 and ranks[0][0] - ranks[1][0] < margin): return None
    value, best = ranks[0]
    log.info("intent fuzzy engine=%s name=%s score=%.1f", engine, best.get("name"), value)
    return dict(best, _fuzzy=True, _fuzzy_score=round(value, 1))
