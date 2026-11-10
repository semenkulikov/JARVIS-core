"""The wake name and the end of a spoken phrase: pure timing and token rules."""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

Word = dict[str, Any]

# Leading tokens that are the name or a call to it («хей», «слушай»), not the command.
PROJECT_NOUN = re.compile(r"проект\w*|сервер\w*|тест\w*|гит\w*|репозитори\w*")
WAKE_TOK = re.compile(r"^(хей|эй|хэй|эх|ай|а|о|ну|слушай|джарвис\w*|жарвис\w*|джервис\w*|дарвис\w*|гарвис\w*|джарви\w*|джави\w*|харвис\w*|травис\w*|арвис\w*|рвис\w*|jarvis)$")
# Recognised spellings of the name itself.
WAKE_NAME = re.compile(r"(?:джарвис|жарвис|джервис|дарвис|гарвис|джарви|джави|харвис|арвис|jarvis)\w*")
# Exact words that may interrupt speech as a priority wake.
PRIORITY_WAKE_WORDS = ("джарвис", "жарвис", "джервис", "дарвис", "гарвис", "джарви", "джави", "jarvis")

# The Vosk wake path starts the capture this far before the end of «Джарвис»; what Vosk makes
# of that tail («крыс», «есть», «то есть») is not the command and must not end the capture.
VOSK_WAKE_TAIL_S = 0.3
VOSK_WAKE_SKIP_S = VOSK_WAKE_TAIL_S + 0.1


def strip_wake(words: Iterable[str]) -> str:
    """Drop the leading name and call words, return the rest as one phrase."""
    toks = list(words)
    while toks and WAKE_TOK.match(toks[0]): toks.pop(0)
    return " ".join(toks).strip()


def strip_wake_words(kept: Sequence[Word]) -> list[Word]:
    """Recognised words after the last name in the first eight, without leading call words."""
    out = list(kept)
    # Strip the recognized wake name, not a fixed 1.35 s of possible command audio.
    wake_indices = [i for i, w in enumerate(out[:8]) if WAKE_NAME.fullmatch(w["word"])]
    # A name that closes a longer phrase is its argument («открой проект джарвис»), not the call.
    if wake_indices and wake_indices[-1] == len(out) - 1 and len(out) >= 2 and PROJECT_NOUN.fullmatch(out[-2]["word"]):
        wake_indices.pop()
    if wake_indices: out = out[wake_indices[-1] + 1:]
    while out and WAKE_TOK.match(out[0]["word"]): out.pop(0)
    return out


def only_wake_heard(words: Sequence[Word], partial: str | None) -> bool:
    """True while everything recognised so far is the wake name (plus «хей» and the like)."""
    toks = [w.get("word", "") for w in words] + (partial or "").split()
    return bool(toks) and all(WAKE_TOK.match(t) for t in toks)


def heard_after(words: Sequence[Word], partial_words: Sequence[Word] | None, partial: str, skip_s: float) -> list[str]:
    """Tokens recognised so far that end after skip_s; without partial timings the partial counts."""
    toks = [w.get("word", "") for w in words if w.get("end", 99) > skip_s]
    if partial_words is not None: toks += [w.get("word", "") for w in partial_words if w.get("end", 99) > skip_s]
    elif partial: toks += partial.split()
    return toks


def phrase_finished(now: float, t0: float, heard: Sequence[str], last_change: float | None, acoustic_last: float | None,
                    nospeech_s: float, sil: float, wake_pause_s: float | None = None, skip_s: float = 0.0) -> bool:
    """End of the utterance: enough silence after speech, or no speech at all within the wait."""
    def quiet(d: float) -> bool:
        return acoustic_last is None or now - acoustic_last > d
    if not heard:
        wait, need = nospeech_s, 0.5
        if wake_pause_s is not None and skip_s > 0:  # only the wake tail so far: answer a bare «Джарвис» soon
            wait, need = min(nospeech_s, skip_s + wake_pause_s), max(0.5, wake_pause_s)
        return now - t0 > wait and quiet(need)
    lim = wake_pause_s if wake_pause_s is not None and all(WAKE_TOK.match(t) for t in heard) else sil
    if not last_change: return False
    return now - last_change > lim and quiet(lim)
