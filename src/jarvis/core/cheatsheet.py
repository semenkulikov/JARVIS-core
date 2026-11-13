"""Cheat-sheet overlay, pure part: what the panel says, the show/hide phrases and the hotkey.

The text is built from the protocol config (jarvis.core.protocols) and the command catalogue the
app passes in (jarvis.commands.catalog), so the panel never drifts from what Jarvis understands.
The window itself is jarvis.adapters.overlay.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from jarvis.core import protocols as PROTOCOLS
from jarvis.core.matching import norm_phrase

CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")
DEFAULTS: dict[str, Any] = {
    "overlay_enabled": True,             # the voice command and the hotkey work; the panel starts hidden
    "overlay_corner": "top-right",
    "overlay_opacity": 0.85,
    "overlay_margin_px": 18,
    "overlay_font_size": 9,
    "overlay_font": "Segoe UI",
    "overlay_hotkey": "ctrl+alt+j",      # empty string: no global hotkey
    "overlay_commands": ["status", "tasks_left", "time", "q:timer", "vol_up", "play", "q:mute", "jarvis_sleep",
                         "proactive_dnd", "q:mode", "q:screenshot", "lock", "stop", "protocol_list", "protocol_cancel",
                         "cheatsheet_hide"],
}
SHOW_PHRASES = ("покажи шпаргалку", "открой шпаргалку", "шпаргалка")
HIDE_PHRASES = ("скрой шпаргалку", "убери шпаргалку", "спрячь шпаргалку", "закрой шпаргалку")
# One word per step, for a protocol without its own ``summary``.
STEP_LABELS = {
    "sleep": "сон", "sleep_until_alarm": "сон до будильника", "cancel_bedtime_repeat": "без повтора отбоя",
    "cancel_repeats": "без повторов", "dnd": "не беспокоить", "media_pause": "пауза", "mute": "без звука",
    "volume": "громкость", "focus": "фокус", "say": "фраза", "beep": "сигнал", "launch": "программы",
    "launch_workspace": "программы", "launch_tracked": "окна", "close_apps": "закрыть программы", "close_all": "закрыть всё",
    "minimize_all": "свернуть", "lock": "блокировка", "hacker_windows": "окна «хакера»", "shutdown": "выключение",
}
TITLE = "Джарвис · шпаргалка"
HINT_HIDE = "«скрой шпаргалку»"
SLEEP_STEPS = ("sleep", "sleep_until_alarm")


@dataclass(frozen=True)
class Line:
    phrase: str
    effect: str


@dataclass(frozen=True)
class Section:
    title: str
    lines: tuple[Line, ...]


# id -> (summary, examples), as in jarvis.commands.catalog.Command
Catalog = Mapping[str, tuple[str, Sequence[str]]]


def protocol_effect(p: PROTOCOLS.Protocol) -> str:
    if p.summary: return p.summary
    labels = list(dict.fromkeys(STEP_LABELS.get(s.name, s.name) for s in p.steps))
    return ", ".join(labels) + (" (с подтверждением)" if p.needs_confirm else "")


def protocol_phrase(p: PROTOCOLS.Protocol) -> str:
    phrase = p.phrases[0]  # the full phrase, «протокол …» included: the router needs it
    return phrase + " [на …]" if any(s.name in SLEEP_STEPS for s in p.steps) else phrase


def build(cfg: Mapping[str, Any], catalog: Catalog) -> list[Section]:
    """Sections of the panel: the protocols, then the configured main commands (unknown ids are skipped)."""
    protos = tuple(Line(protocol_phrase(p), protocol_effect(p)) for p in PROTOCOLS.parse(cfg))
    ids = cfg.get("overlay_commands", DEFAULTS["overlay_commands"])
    cmds = tuple(Line(catalog[i][1][0], _effect(catalog[i][1][0], catalog[i][0])) for i in (ids if isinstance(ids, list) else [])
                 if i in catalog and catalog[i][1])
    return [s for s in (Section("Протоколы", protos), Section("Основные команды", cmds)) if s.lines]


def _effect(phrase: str, summary: str) -> str:
    """The summary, or nothing when it only repeats the phrase («который час» — «Который час»)."""
    return "" if summary.strip().lower() == phrase.strip().lower() else summary


def render_text(sections: Sequence[Section]) -> str:
    """Plain text of the panel (for the log and the tests)."""
    out = [TITLE]
    for s in sections:
        out += ["", s.title.upper()] + [("«%s» — %s" % (ln.phrase, ln.effect)) if ln.effect else "«%s»" % ln.phrase for ln in s.lines]
    return "\n".join(out)


def intent(text: str) -> dict[str, Any] | None:
    joined = " ".join(norm_phrase(text))
    if joined in SHOW_PHRASES: return {"name": "cheatsheet_show", "action": "overlay", "visible": True}
    if joined in HIDE_PHRASES: return {"name": "cheatsheet_hide", "action": "overlay", "visible": False}
    return None


def phrases() -> list[str]:
    """Show and hide phrases, for the vocabulary check of the Vosk model."""
    return list(SHOW_PHRASES) + list(HIDE_PHRASES)


def aliases() -> list[dict[str, Any]]:
    """Router and grammar entries for the show and hide phrases."""
    return [{"name": "cheatsheet_show", "action": "overlay", "visible": True, "phrases": list(SHOW_PHRASES), "extra_words": 0},
            {"name": "cheatsheet_hide", "action": "overlay", "visible": False, "phrases": list(HIDE_PHRASES), "extra_words": 0}]


MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
NO_REPEAT = 0x4000


def parse_hotkey(spec: Any) -> tuple[int, int] | None:
    """(RegisterHotKey modifiers, virtual key) for «ctrl+alt+j»; None when empty or invalid.
    At least one of ctrl/alt/win is required, so a plain key is never grabbed system-wide."""
    if not isinstance(spec, str) or not spec.strip(): return None
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if len(parts) < 2: return None
    mods = 0
    for p in parts[:-1]:
        if p not in MODIFIERS: return None
        mods |= MODIFIERS[p]
    key = parts[-1]
    if len(key) == 1 and (key.isascii() and key.isalnum()): vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24: vk = 0x6F + int(key[1:])
    else: return None
    if not mods & (MODIFIERS["ctrl"] | MODIFIERS["alt"] | MODIFIERS["win"]): return None
    return mods | NO_REPEAT, vk


def corner(cfg: Mapping[str, Any]) -> str:
    c = cfg.get("overlay_corner", DEFAULTS["overlay_corner"])
    return str(c) if c in CORNERS else CORNERS[0]


def opacity(cfg: Mapping[str, Any]) -> float:
    try: v = float(cfg.get("overlay_opacity", DEFAULTS["overlay_opacity"]))
    except (TypeError, ValueError): v = DEFAULTS["overlay_opacity"]
    return min(1.0, max(0.3, v))


def position(corner_name: str, size: tuple[int, int], screen: tuple[int, int], margin: int) -> tuple[int, int]:
    """Top-left pixel of a panel of ``size`` in a screen corner."""
    w, h = size; sw, sh = screen
    x = margin if corner_name.endswith("left") else max(0, sw - w - margin)
    y = margin if corner_name.startswith("top") else max(0, sh - h - margin - 40)  # keep clear of the taskbar
    return x, y
