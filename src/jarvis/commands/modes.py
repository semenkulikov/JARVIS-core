"""Assistant modes: the local sleep mode and «не беспокоить» for proactive notices."""
from __future__ import annotations

import logging

from jarvis.core import proactive as PROACTIVE
from jarvis.core import sleep as SLEEP
from jarvis.commands.base import Alias, CommandContext
from jarvis.commands.registry import handles

log = logging.getLogger("jarvis")
OVERLAY_REPLIES = {True: "Шпаргалка на экране, сэр.", False: "Убрал шпаргалку, сэр."}
OVERLAY_OFF = "Шпаргалка выключена в настройках, сэр."


@handles("jarvis_sleep")
def sleep(ctx: CommandContext, al: Alias) -> None:
    s = ctx.services
    s.state.followup_eligible = False
    secs = int(al["seconds"])
    if ctx.test: log.info("TEST sleep %ss: no persistent change", secs)
    else: s.sleep().start(secs)
    s.say(SLEEP.enter_phrase(secs), ctx.cfg)


@handles("proactive_dnd")
def do_not_disturb(ctx: CommandContext, al: Alias) -> None:
    if ctx.test: log.info("TEST DND=%s: no persistent change", al["enabled"])
    else: ctx.services.proactive().set_dnd(al["enabled"])
    ctx.services.say(PROACTIVE.REPLIES[0 if al["enabled"] else 1], ctx.cfg)


@handles("overlay")
def cheatsheet(ctx: CommandContext, al: Alias) -> None:
    """«покажи шпаргалку» / «скрой шпаргалку»: the translucent panel; showing is silent apart from a short line."""
    overlay = ctx.services.overlay()
    visible = bool(al.get("visible", True))
    if overlay is None or (visible and not overlay.show()): ctx.services.say(OVERLAY_OFF, ctx.cfg); return
    if not visible: overlay.hide()
    ctx.services.say(OVERLAY_REPLIES[visible], ctx.cfg)
