"""Conversational acknowledgements: which command gets an instant «Есть, сэр» and how it overlaps the work.

Pure policy plus one small helper; the voice loop owns audio. Ack phrases live in config
(lists, never the same one twice in a row) and are pre-synthesised at startup, so the ack
starts with near-zero latency while the command runs in parallel.
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional

DEFAULTS: Dict[str, object] = {
    "ack_wake": ["Да, сэр?", "Слушаю, сэр.", "Я здесь, сэр.", "К вашим услугам, сэр."],
    "ack_action": ["Есть, сэр.", "Выполняю, сэр.", "Как прикажете, сэр.", "Сейчас, сэр.", "Слушаюсь, сэр."],
    "ack_lookup": ["Сейчас, сэр.", "Секунду, сэр.", "Смотрю, сэр.", "Проверяю, сэр."],
    "ack_food": ["Записываю, сэр.", "Есть, сэр, записываю."],
    "ack_server": ["Сейчас, сэр.", "Секунду, сэр.", "Одну секунду, сэр.", "Минуту, сэр."],
    "wake_ack_after_s": 0.7,
}
# Stress marks (Silero '+') for words the acks and sleep phrases use.
STRESS = {w.replace("+", ""): w for w in ["выполн+яю", "сл+ушаю", "сл+ушаюсь", "просн+ись", "разбуд+ить", "сп+ящий", "сп+ящем", "реж+име",
                                           "зап+исываю", "смотр+ю", "провер+яю", "прик+ажете", "усл+угам", "ух+ожу", "полтор+а"]}
ACK_KEYS = ("ack_action", "ack_lookup", "ack_food", "ack_server")

# Quick commands whose answer is instant (an ack would only add delay), that ask a question,
# or that hand over to the server, whose own varied ack plays while the request runs.
_ACTION = {"screenshot", "timer", "reminder", "note", "mode", "project_tests", "close_window"}
_LOOKUP = {"server_health", "nutrition_left", "git"}
_FOOD = {"food_log"}


def ack_key(alias: Optional[dict]) -> Optional[str]:
    """Config key of the ack list for a matched quick command, or None for no ack."""
    if not alias or alias.get("action") != "quick2":
        return None
    cmd = alias.get("cmd")
    if cmd == "mode" and alias.get("mode") == "sleep":
        return None  # speaks its own «Режим сна, сэр…» before the screen goes dark
    if cmd in _ACTION:
        return "ack_action"
    if cmd in _LOOKUP:
        return "ack_lookup"
    if cmd in _FOOD:
        return "ack_food"
    return None


def ack_then(say: Callable, cfg: dict, ack: str, work: Callable[[Callable], object],
             thread_name: str = "ack-work"):
    """Speak ``ack`` now while ``work(gated_say)`` runs in parallel; return work's result.

    Audio stays sequential: the worker's say calls wait until the ack has finished.
    Exceptions from work are re-raised in the caller.
    """
    if not ack:
        return work(say)
    spoken = threading.Event()
    box: Dict[str, object] = {}

    def gated_say(text, c=None, **kw):
        spoken.wait()
        return say(text, cfg if c is None else c, **kw)

    def run():
        try:
            box["value"] = work(gated_say)
        except BaseException as e:  # re-raised below
            box["error"] = e

    th = threading.Thread(target=run, name=thread_name, daemon=True)
    th.start()
    try:
        say(ack, cfg, role="ack")
    finally:
        spoken.set()
    th.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value")


def phrase_lists(cfg: dict) -> List[str]:
    """Every ack phrase from this module, for the startup TTS cache."""
    out: List[str] = []
    for key in ("ack_wake",) + ACK_KEYS:
        v = cfg.get(key) or DEFAULTS[key]
        out += [v] if isinstance(v, str) else list(v)
    return [x for x in out if x]
