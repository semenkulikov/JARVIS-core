"""Input gate: decides whether recognised speech is really meant for Jarvis.

Pure functions over Vosk word lists (``{"word", "conf", "start", "end"}``) so the
listener stays testable without audio. Everything rejected here is dropped silently.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

Word = Mapping[str, Any]

WAKE_NAME = re.compile(r"(?:джарвис|жарвис|джервис|дарвис|гарвис|джарви|джави|харвис|jarvis)\w*")
WAKE_PREFIX = {"хей", "эй", "хэй"}

DEFAULTS: dict[str, Any] = {
    "wake_verify_enabled": True,     # second, free-vocabulary check of every grammar/oww wake
    "wake_verify_min_conf": 0.7,     # confidence of the wake name in the free transcript
    "wake_verify_owner_min_conf": 0.3,  # enough when the owner's voice is confirmed by the speaker check
    "sleep_wake_min_conf": 0.85,     # «Джарвис, проснись» while asleep: stricter
    "wake_verify_pre_s": 0.6,        # audio taken before the grammar word start
    "wake_verify_post_s": 0.45,      # audio taken after the grammar word end
    "wake_verify_normalize": True,   # lift the whole verify clip towards a target peak (quiet, far-field speech)
    "wake_verify_target_peak": 0.7,
    "wake_verify_max_gain": 30.0,
    "wake_verify_pad_s": 0.2,        # silence around the verify clip for the free recognizer
    "oww_strong_threshold": 0.9,     # openWakeWord score accepted without free-transcript proof
    "command_min_conf": 0.7,         # average confidence for a phrase sent to the server
    "command_max_words": 20,
    "followup_gate_min_conf": 0.8,   # follow-ups (no wake word) must be clearly spoken
    "followup_max_words": 10,
    "followup_window_cap_s": 6.0,    # hard cap on the no-wake-word listening window
    "unsure_word_conf": 0.6,
    "max_unsure_ratio": 0.34,
}


def setting(cfg: Mapping[str, Any], key: str) -> Any:
    return cfg.get(key, DEFAULTS[key])


def wake_word_confirmed(words: Sequence[Word], min_conf: float) -> bool:
    """True when a free-vocabulary transcript contains the wake name with high confidence."""
    return any(WAKE_NAME.fullmatch(str(w.get("word", ""))) and float(w.get("conf", 0)) >= min_conf for w in words)


def avg_conf(words: Sequence[Word]) -> float:
    return sum(float(w.get("conf", 0)) for w in words) / len(words) if words else 0.0


def reject_reason(words: Sequence[Word], cfg: Mapping[str, Any], *, followup: bool, hit_max: bool) -> Optional[str]:
    """Why a free phrase must not reach the server (None = looks like a real command)."""
    if not words:
        return "empty"
    if hit_max:
        return "continuous_speech"  # nobody pauses -> TV, lesson, call audio
    min_conf = float(setting(cfg, "followup_gate_min_conf" if followup else "command_min_conf"))
    if avg_conf(words) < min_conf:
        return "low_confidence"
    if len(words) > int(setting(cfg, "followup_max_words" if followup else "command_max_words")):
        return "too_long"
    unsure = sum(1 for w in words if float(w.get("conf", 0)) < float(setting(cfg, "unsure_word_conf")))
    if unsure / len(words) > float(setting(cfg, "max_unsure_ratio")):
        return "unsure_words"
    return None


def is_silent_reply(text: Optional[str]) -> bool:
    """Server marker meaning: finish the request without speaking."""
    t = (text or "").strip().lower()
    return t in ("", "<silent>", "[silent]", "<тишина>")
