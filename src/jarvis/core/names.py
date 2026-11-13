"""Wake names: the one source of the name grammar, the name rules and the wake phrases.

«Джарвис» is the primary name: every recognised spelling counts (with an ending), and only it may
interrupt speech as a priority wake. The other names («нуб», «кусок железа», ...) are exact word
sequences; two-word names are matched as sequences everywhere. A name whose word the Vosk model
does not know is left out (see :meth:`NameSet.from_cfg` ``missing``), otherwise it would silently
never fire. openWakeWord only knows «hey Jarvis», so the other names go through the Vosk grammar
and the free-recognizer check like a weak «Джарвис».
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Collection, Iterable, Mapping, Sequence

from jarvis.core.fold import fold

Word = Mapping[str, Any]

PRIMARY = "джарвис"
# Spellings the recognizers make of «Джарвис»; a token counts as the name with any ending.
SPELLINGS = ("джарвис", "жарвис", "джервис", "дарвис", "гарвис", "джарви", "джави", "харвис", "арвис", "jarvis")
# Seen only at the head of a phrase, where they are dropped as part of the call, never taken as the name.
HEAD_FRAGMENTS = ("травис", "рвис")
# Exact words that may interrupt speech as a priority wake: «Джарвис» only, short names must not.
PRIORITY_WORDS = ("джарвис", "жарвис", "джервис", "дарвис", "гарвис", "джарви", "джави", "jarvis")
GRAMMAR_PREFIXES = ("хей", "эй")
# Call words in front of a name («хей», «слушай»): dropped with it.
CALL_WORDS = frozenset({"хей", "эй", "хэй", "эх", "ай", "а", "о", "ну", "слушай"})
ALIASES = ("нуб", "нубас", "кусок железа", "жестянка", "железяка", "железка")
WAKE_VERB = "проснись"
DEFAULTS: dict[str, Any] = {
    "wake_names": [{"name": n, "enabled": True} for n in ALIASES],  # built-in extra names, each can be switched off
    "wake_names_extra": [],            # own names: "имя" or {"name": "имя", "enabled": true, "ack": "Слушаю, сэр."}
    "wake_alias_min_conf": 0.85,       # every word of a name other than «Джарвис» must be this sure
}

_PRIMARY_RE = re.compile(r"(?:%s)\w*" % "|".join(SPELLINGS))
_HEAD_RE = re.compile(r"(?:%s)\w*" % "|".join(SPELLINGS + HEAD_FRAGMENTS))


def _words(name: str) -> tuple[str, ...]:
    return tuple(re.sub(r"[^\w\s]", " ", fold(name)).split())


@dataclass(frozen=True)
class WakeName:
    words: tuple[str, ...]
    primary: bool = False
    ack: str = ""

    @property
    def text(self) -> str:
        return " ".join(self.words)


class NameSet:
    """The enabled wake names with every rule that depends on them. Immutable; build one per configuration."""

    def __init__(self, names: Iterable[WakeName]) -> None:
        self.names: tuple[WakeName, ...] = tuple(names)
        self.aliases = tuple(n for n in self.names if not n.primary)
        self.has_primary = any(n.primary for n in self.names)

    @classmethod
    def from_cfg(cls, cfg: Mapping[str, Any], missing: Collection[str] = ()) -> NameSet:
        """«Джарвис» plus the enabled built-in and own names; names with a word in ``missing`` are left out."""
        out = [WakeName((PRIMARY,), primary=True)]
        seen: set[tuple[str, ...]] = {(PRIMARY,)}
        for raw in list(cfg.get("wake_names", DEFAULTS["wake_names"]) or []) + list(cfg.get("wake_names_extra") or []):
            item = {"name": raw} if isinstance(raw, str) else raw if isinstance(raw, dict) else {}
            words = _words(str(item.get("name", "")))
            if not words or words in seen or not item.get("enabled", True) or any(w in missing for w in words): continue
            seen.add(words); out.append(WakeName(words, ack=str(item.get("ack") or "")))
        return cls(out)

    # ------------------------------------------------------------ token rules
    @staticmethod
    def is_primary(token: str) -> bool:
        return bool(_PRIMARY_RE.fullmatch(token))

    def match_at(self, toks: Sequence[str], i: int, head: bool = False) -> int:
        """Tokens a name takes at ``toks[i]`` (0 = no name there); ``head`` also accepts fragments of «Джарвис»."""
        if i >= len(toks): return 0
        t = fold(toks[i])
        if self.has_primary and (_HEAD_RE if head else _PRIMARY_RE).fullmatch(t): return 1
        for n in self.aliases:
            k = len(n.words)
            if tuple(fold(x) for x in toks[i:i + k]) == n.words: return k
        return 0

    def strip(self, toks: Sequence[str]) -> list[str]:
        """Drop the leading names and call words («хей кусок железа, громче» -> «громче»)."""
        out = list(toks); i = 0
        while i < len(out):
            if fold(out[i]) in CALL_WORDS: i += 1; continue
            k = self.match_at(out, i, head=True)
            if not k: break
            i += k
        return out[i:]

    def only_names(self, toks: Sequence[str]) -> bool:
        """True while everything heard is names and call words (and something was heard)."""
        return bool(toks) and not self.strip(toks)

    def spans(self, toks: Sequence[str], within: int | None = None) -> list[tuple[int, int, WakeName]]:
        """(start, end, name) of every name in ``toks`` (the first ``within`` tokens), left to right."""
        out: list[tuple[int, int, WakeName]] = []; i = 0; limit = len(toks) if within is None else min(len(toks), within)
        while i < limit:
            k = self.match_at(toks, i)
            if k:
                name = self.names[0] if self.has_primary and self.is_primary(fold(toks[i])) else self._alias(toks[i:i + k])
                out.append((i, i + k, name)); i += k
            else: i += 1
        return out

    def _alias(self, toks: Sequence[str]) -> WakeName:
        words = tuple(fold(t) for t in toks)
        return next(n for n in self.aliases if n.words == words)

    def confirmed(self, words: Sequence[Word], min_conf: float, alias_min_conf: float) -> bool:
        """A free transcript holds a name confidently: «Джарвис» at ``min_conf``, every word of another name at
        the stricter ``max(min_conf, alias_min_conf)``."""
        toks = [str(w.get("word", "")) for w in words]
        for a, b, name in self.spans(toks):
            need = min_conf if name.primary else max(min_conf, alias_min_conf)
            if all(float(words[j].get("conf", 0)) >= need for j in range(a, b)): return True
        return False

    # ------------------------------------------------------------ phrase lists
    def grammar(self) -> list[str]:
        """Phrases of the narrow wake recognizer."""
        out: list[str] = []
        for n in self.names:
            out += [n.text] + [p + " " + n.text for p in GRAMMAR_PREFIXES]
        return out + ["[unk]"]

    def wake_phrases(self) -> tuple[str, ...]:
        """Phrases that end sleep mode: «<имя> проснись», «проснись <имя>», «хей <имя> проснись»."""
        out: list[str] = []
        for n in self.names:
            out += [f"{n.text} {WAKE_VERB}", f"{WAKE_VERB} {n.text}", f"хей {n.text} {WAKE_VERB}"]
        return tuple(out)

    def hint_phrases(self) -> tuple[str, ...]:
        """A bare name while asleep: answered with a hint how to wake up."""
        return tuple(n.text for n in self.names)

    def vocabulary(self) -> set[str]:
        """Every word the name grammars use, for the start-up check against the model."""
        return {w for n in self.names for w in n.words} | set(GRAMMAR_PREFIXES) | {WAKE_VERB}


DEFAULT = NameSet.from_cfg(DEFAULTS)
