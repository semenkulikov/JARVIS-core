"""Talk that needs no data: plain replies, small talk, stop, «проснись», «что ты умеешь»."""
from __future__ import annotations

import logging

from jarvis.commands import catalog as REGISTRY
from jarvis.core import tasks as TASKS
from jarvis.commands.base import Alias, CommandContext
from jarvis.commands.registry import handles
from jarvis.core.phrases import smalltalk_reply

log = logging.getLogger("jarvis")


@handles("say")
def say_alias_reply(ctx: CommandContext, al: Alias) -> None:
    """Default for any alias without its own handler: speak its configured reply."""
    ctx.services.say(al.get("reply") or "", ctx.cfg)


@handles("smalltalk")
def smalltalk(ctx: CommandContext, al: Alias) -> None:
    ctx.services.say(smalltalk_reply(al, ctx.services.picker), ctx.cfg)


@handles("stop")
def stop(ctx: CommandContext, al: Alias) -> None:
    s = ctx.services
    s.say(s.pick(ctx.cfg, "ack_stop"), ctx.cfg, role="stop_ack")


@handles("awake")
def awake(ctx: CommandContext, al: Alias) -> None:
    ctx.services.say(TASKS.AWAKE_REPLY, ctx.cfg)


@handles("capabilities")
def capabilities(ctx: CommandContext, al: Alias) -> None:
    for line in REGISTRY.log_lines(): log.info("capabilities: %s", line)
    ctx.services.say_reply(REGISTRY.capabilities_phrase(), ctx.cfg)
