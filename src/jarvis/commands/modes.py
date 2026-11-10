"""Assistant modes: the local sleep mode and «не беспокоить» for proactive notices."""
from __future__ import annotations

import logging

import jarvis_proactive as PROACTIVE
import jarvis_sleep as SLEEP
from jarvis.commands.base import Alias, CommandContext
from jarvis.commands.registry import handles

log = logging.getLogger("jarvis")


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
