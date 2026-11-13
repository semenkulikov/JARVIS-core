"""The wake name at the head of a phrase and the end of a spoken phrase: pure timing and token rules.

The names themselves live in jarvis.core.names."""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from jarvis.core.names import DEFAULT as NAMES
from jarvis.core.names import PRIORITY_WORDS, NameSet

Word = dict[str, Any]

PROJECT_NOUN = re.compile(r"проект\w*|сервер\w*|тест\w*|гит\w*|репозитори\w*")
# Exact words that may interrupt speech as a priority wake (jarvis.core.names: «Джарвис» only).
PRIORITY_WAKE_WORDS = PRIORITY_WORDS

# The Vosk wake path starts the capture this far before the end of «Джарвис»; what Vosk makes
# of that tail («крыс», «есть», «то есть») is not the command and must not end the capture.
VOSK_WAKE_TAIL_S = 0.3
VOSK_WAKE_SKIP_S = VOSK_WAKE_TAIL_S + 0.1


def strip_wake(words: Iterable[str], names: NameSet = NAMES) -> str:
    """Drop the leading names and call words, return the rest as one phrase."""
    return " ".join(names.strip(list(words))).strip()


def strip_wake_words(kept: Sequence[Word], names: NameSet = NAMES) -> list[Word]:
    """Recognised words after the last name in the first eight, without leading call words."""
    out = list(kept)
    toks = [str(w["word"]) for w in out]
    # Strip the recognized wake name, not a fixed 1.35 s of possible command audio.
    spans = names.spans(toks, within=8)
    # A name that closes a longer phrase is its argument («открой проект джарвис»), not the call.
    if spans and spans[-1][1] == len(out) and spans[-1][0] >= 1 and PROJECT_NOUN.fullmatch(toks[spans[-1][0] - 1]):
        spans.pop()
    if spans: out = out[spans[-1][1]:]
    rest = names.strip([str(w["word"]) for w in out])
    return out[len(out) - len(rest):]


def only_wake_heard(words: Sequence[Word], partial: str | None, names: NameSet = NAMES) -> bool:
    """True while everything recognised so far is a wake name (plus «хей» and the like)."""
    toks = [w.get("word", "") for w in words] + (partial or "").split()
    return names.only_names(toks)


def heard_after(words: Sequence[Word], partial_words: Sequence[Word] | None, partial: str, skip_s: float) -> list[str]:
    """Tokens recognised so far that end after skip_s; without partial timings the partial counts."""
    toks = [w.get("word", "") for w in words if w.get("end", 99) > skip_s]
    if partial_words is not None: toks += [w.get("word", "") for w in partial_words if w.get("end", 99) > skip_s]
    elif partial: toks += partial.split()
    return toks


def phrase_finished(now: float, t0: float, heard: Sequence[str], last_change: float | None, acoustic_last: float | None,
                    nospeech_s: float, sil: float, wake_pause_s: float | None = None, skip_s: float = 0.0,
                    names: NameSet = NAMES) -> bool:
    """End of the utterance: enough silence after speech, or no speech at all within the wait."""
    def quiet(d: float) -> bool:
        return acoustic_last is None or now - acoustic_last > d
    if not heard:
        wait, need = nospeech_s, 0.5
        if wake_pause_s is not None and skip_s > 0:  # only the wake tail so far: answer a bare «Джарвис» soon
            wait, need = min(nospeech_s, skip_s + wake_pause_s), max(0.5, wake_pause_s)
        return now - t0 > wait and quiet(need)
    lim = wake_pause_s if wake_pause_s is not None and names.only_names(heard) else sil
    if not last_change: return False
    return now - last_change > lim and quiet(lim)
