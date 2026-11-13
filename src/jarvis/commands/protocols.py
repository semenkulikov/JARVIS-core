"""Protocols: one phrase runs a chain of steps (config ``protocols``, rules in jarvis.core.protocols).

Each step is a small function in :data:`STEPS`. Steps run in order; a failing step is logged and
the rest still run; one reply is spoken at the end. A protocol with ``confirm`` (or a shutdown
step) first asks for a spoken «да», like the shutdown command. Nothing runs in a test turn
against the real desktop.
"""
from __future__ import annotations

import functools
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis.commands.base import Alias, CommandContext
from jarvis.commands.registry import handles
from jarvis.core import protocols as PROTOCOLS
from jarvis.core import sleep as SLEEP
from jarvis.core.protocols import Protocol, Step

log = logging.getLogger("jarvis")

# The only commands «Взлом Пентагона» may open: read-only system listings. The owner extends this
# tuple by hand; the config cannot add commands, so a voice protocol never runs arbitrary code.
HACKER_COMMANDS: tuple[str, ...] = ("dir /s", "driverquery", "tasklist", "systeminfo", "netstat -ano", "tree")
HACKER_CWD = os.environ.get("SystemRoot", r"C:\Windows")
ALARM_ENTRY = "wake_up"
CANCELLED = "Протокол отменён, сэр."
NOT_CONFIRMED = "Протокол не подтверждён, сэр."
NONE_CONFIGURED = "Протоколы не настроены, сэр."


@dataclass
class Run:
    """One protocol run: the turn, the protocol, the duration said («на шесть часов») and step notes."""

    ctx: CommandContext
    protocol: Protocol
    seconds: int | None
    failed: list[str] = field(default_factory=list)

    @property
    def backend(self) -> Any: return self.ctx.services.controller().backend


StepFn = Callable[[Run, Step], None]


def _sleep(run: Run, step: Step) -> None:
    secs = run.seconds or int(step.params.get("seconds") or SLEEP.DEFAULT_S)
    run.ctx.services.sleep().start(min(SLEEP.MAX_S, secs))


def _sleep_until_alarm(run: Run, step: Step) -> None:
    """Sleep until the schedule alarm (it ends sleep silently and speaks), or for the duration said."""
    s = run.ctx.services
    if run.seconds: s.sleep().start(run.seconds); return
    at = s.proactive().next_at(run.ctx.cfg, str(step.params.get("entry") or ALARM_ENTRY))
    secs = (at - time.time()) if at else 0
    if 0 < secs <= SLEEP.MAX_S: s.sleep().start(secs, quiet_end=True)
    else: s.sleep().start(SLEEP.DEFAULT_S if not secs else SLEEP.MAX_S)


def _cancel_repeats(run: Run, step: Step) -> None:
    run.ctx.services.proactive().cancel_repeats(run.ctx.cfg, step.params.get("entry"))


def _dnd(run: Run, step: Step) -> None: run.ctx.services.proactive().set_dnd(bool(step.params.get("enabled", True)))
def _media_pause(run: Run, step: Step) -> None: run.backend.media(False)
def _mute(run: Run, step: Step) -> None: run.backend.mute(bool(step.params.get("muted", True)))
def _volume(run: Run, step: Step) -> None: run.backend.volume(max(0.0, min(100.0, float(step.params.get("value", 30)))))
def _focus(run: Run, step: Step) -> None: run.ctx.services.controller().start_focus(run.ctx.cfg)
def _say(run: Run, step: Step) -> None: run.ctx.services.say(str(step.params.get("text") or ""), run.ctx.cfg)
def _beep(run: Run, step: Step) -> None: run.ctx.services.beep()
def _minimize_all(run: Run, step: Step) -> None: run.backend.minimize_all()
def _lock(run: Run, step: Step) -> None: run.backend.lock()
def _shutdown(run: Run, step: Step) -> None: run.backend.shutdown(max(60, int(step.params.get("seconds", 60))))


def _launch(run: Run, step: Step) -> None:
    targets = step.params.get("targets") or run.ctx.cfg.get("workspace") or []
    if not targets: log.info("protocol launch: workspace is empty"); return
    for t in targets:  # one bad entry must not stop the others
        try: run.backend.launch(str(t))
        except Exception as e: log.warning("protocol launch %r failed (%s)", t, type(e).__name__); run.failed.append("launch")


def _launch_tracked(run: Run, step: Step) -> None:
    """Windows «отмена протокола» closes later (e.g. the owner's server sessions from the local file).
    Targets are not logged: they may name private hosts or paths."""
    ctl = run.ctx.services.controller(); targets = step.params.get("targets") or []
    for i, t in enumerate(targets):
        try: ctl.protocol_pids.append(run.backend.open_window(str(t)))
        except Exception as e: log.warning("protocol window #%d failed (%s)", i + 1, type(e).__name__); run.failed.append("launch_tracked")
    log.info("protocol launch_tracked: %d of %d windows open", len(targets) - run.failed.count("launch_tracked"), len(targets))


def _window_spec(item: Any) -> tuple[str, str | None, str | None] | None:
    """A launch target, optional place (``left_half`` / ``right_half``) and optional window title."""
    if isinstance(item, str) and item.strip(): return item.strip(), None, None
    if not isinstance(item, dict): return None
    target = str(item.get("target") or item.get("path") or "").strip()
    if not target: return None
    place = item.get("place"); title = item.get("title")
    return (target,
            place.strip() if isinstance(place, str) and place.strip() else None,
            title.strip() if isinstance(title, str) and title.strip() else None)


def _launch_placed(run: Run, step: Step) -> None:
    """Open targets in the default terminal and snap each to a named half of the primary
    work area. «отмена протокола» closes them. Targets are not logged: they may be private."""
    ctl = run.ctx.services.controller(); windows = step.params.get("windows") or step.params.get("targets") or []
    if not isinstance(windows, list): windows = []
    opened = 0
    for i, item in enumerate(windows):
        spec = _window_spec(item)
        if spec is None:
            log.warning("protocol placed window #%d skipped: bad entry", i + 1); run.failed.append("launch_placed"); continue
        target, place, title = spec
        try:
            ctl.protocol_pids.append(run.backend.open_window(target, place=place, title=title)); opened += 1
        except Exception as e:
            log.warning("protocol placed window #%d failed (%s)", i + 1, type(e).__name__); run.failed.append("launch_placed")
    log.info("protocol launch_placed: %d of %d windows open", opened, len(windows))


def _close_apps(run: Run, step: Step) -> None:
    names = [str(x) for x in (step.params.get("apps") or run.ctx.cfg.get("close_apps") or [])]
    closed = run.backend.close_apps(names, {os.getpid(), os.getppid()}) if names else 0
    log.info("protocol close_apps: asked %d windows to close", closed)


def _close_all(run: Run, step: Step) -> None:
    closed = run.backend.close_windows({os.getpid(), os.getppid()})
    log.info("protocol close_all: asked %d windows to close", closed)


def _hacker_windows(run: Run, step: Step) -> None:
    ctl = run.ctx.services.controller(); b = run.backend
    n = max(1, min(len(HACKER_COMMANDS), int(step.params.get("count") or run.ctx.cfg.get("protocol_hacker_windows", 6))))
    width, height = b.screen_size()
    for i, (cmd, rect) in enumerate(zip(HACKER_COMMANDS[:n], PROTOCOLS.grid(n, width, height), strict=True)):
        try: ctl.protocol_pids.append(b.open_console(cmd, "PENTAGON %d" % (i + 1), rect, HACKER_CWD))
        except Exception as e: log.warning("protocol window %r failed (%s)", cmd, type(e).__name__); run.failed.append("hacker_windows")


STEPS: dict[str, StepFn] = {
    "sleep": _sleep, "sleep_until_alarm": _sleep_until_alarm, "cancel_bedtime_repeat": _cancel_repeats, "cancel_repeats": _cancel_repeats,
    "dnd": _dnd, "media_pause": _media_pause, "mute": _mute, "volume": _volume, "focus": _focus, "say": _say, "beep": _beep,
    "launch": _launch, "launch_workspace": _launch, "launch_tracked": _launch_tracked, "launch_placed": _launch_placed, "close_apps": _close_apps, "close_all": _close_all, "minimize_all": _minimize_all, "lock": _lock,
    "hacker_windows": _hacker_windows, "shutdown": _shutdown,
}
SLEEP_STEPS = frozenset({"sleep", "sleep_until_alarm"})


def find(cfg: Any, name: str) -> Protocol | None:
    return next((p for p in PROTOCOLS.parse(cfg) if p.name == name), None)


def run_steps(ctx: CommandContext, protocol: Protocol, seconds: int | None) -> Run:
    """Every step in order; one failure is logged and does not stop the rest. No reply here."""
    run = Run(ctx, protocol, seconds)
    for step in protocol.steps:
        fn = STEPS.get(step.name)
        if fn is None: log.warning("protocol %s: unknown step %r skipped", protocol.name, step.name); run.failed.append(step.name); continue
        try: fn(run, step); log.info("protocol %s: step %s done", protocol.name, step.name)
        except Exception as e: log.warning("protocol %s: step %s failed (%s)", protocol.name, step.name, type(e).__name__); run.failed.append(step.name)
    return run


def _execute(ctx: CommandContext, protocol: Protocol, seconds: int | None) -> None:
    s = ctx.services
    if any(st.name in SLEEP_STEPS for st in protocol.steps): s.state.followup_eligible = False
    if ctx.test and not s.controller().backend.is_fake:
        log.info("TEST protocol %s: steps %s suppressed", protocol.name, [st.name for st in protocol.steps])
    else:
        run = run_steps(ctx, protocol, seconds)
        if run.failed: log.info("protocol %s finished with failed steps %s", protocol.name, run.failed)
    s.say(protocol.reply, ctx.cfg)


@handles("protocol")
def protocol(ctx: CommandContext, al: Alias) -> None:
    s = ctx.services; p = find(ctx.cfg, str(al.get("protocol")))
    if p is None: s.say(NONE_CONFIGURED, ctx.cfg); return
    seconds = al.get("seconds")
    if p.needs_confirm:
        steps = ", ".join(st.name for st in p.steps)
        log.info("protocol %s waits for confirmation (steps %s)", p.name, steps)
        if s.say("Протокол «" + p.name + "». Подтверждаете? Скажите да.", ctx.cfg):
            s.controller().ask("protocol", ctx.cfg, protocol=p.name, seconds=seconds)
        return
    _execute(ctx, p, seconds)


@handles("protocol_confirm")
def confirmed(ctx: CommandContext, al: Alias) -> None:
    s = ctx.services; p = find(ctx.cfg, str(al.get("protocol")))
    if not al.get("approved") or p is None:
        log.info("protocol %s not confirmed (%s)", al.get("protocol"), al.get("reason", "no"))
        s.say(NOT_CONFIRMED, ctx.cfg); return
    _execute(ctx, p, al.get("seconds"))


@handles("protocol_list")
def protocol_list(ctx: CommandContext, al: Alias) -> None:
    names = [p.name for p in PROTOCOLS.parse(ctx.cfg)]
    ctx.services.say("Протоколы: " + ", ".join(names) + ", сэр." if names else NONE_CONFIGURED, ctx.cfg)


@handles("protocol_cancel")
def protocol_cancel(ctx: CommandContext, al: Alias) -> None:
    """Close the «взлом» windows, lift «не беспокоить», mute and sleep."""
    s = ctx.services; ctl = s.controller()
    if ctx.test and not ctl.backend.is_fake: log.info("TEST protocol cancel suppressed"); s.say(CANCELLED, ctx.cfg); return
    undo: list[tuple[str, Callable[[], Any]]] = [(f"window {pid}", functools.partial(ctl.backend.end_process, pid)) for pid in ctl.protocol_pids]
    undo += [("dnd", lambda: s.proactive().set_dnd(False)), ("mute", lambda: ctl.backend.mute(False)),
             ("sleep", lambda: s.sleep().stop("protocol_cancel"))]
    for what, fn in undo:
        try: fn()
        except Exception as e: log.warning("protocol cancel: %s failed (%s)", what, type(e).__name__)
    ctl.protocol_pids.clear()
    s.say(CANCELLED, ctx.cfg)
