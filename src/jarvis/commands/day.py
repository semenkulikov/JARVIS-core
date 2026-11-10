"""Status, tasks, time and the workout schedule: local snapshot first, the server when it is stale."""
from __future__ import annotations

import datetime
import logging

from jarvis.core import tasks as TASKS
import jarvis_text as JT
from jarvis.commands.base import Alias, CommandContext
from jarvis.commands.registry import handles
from jarvis.core.schedule import workout_summary

log = logging.getLogger("jarvis")


@handles("status", "cache_field")
def status(ctx: CommandContext, al: Alias) -> None:
    s, cfg, text = ctx.services, ctx.cfg, ctx.text
    field = al.get("field") if al.get("action") == "cache_field" else None
    decision, cached, age = s.status.cached_status(field, cfg)
    log.info("status cache policy=%s field=%s age_h=%s", decision, field or "all", None if age is None else round(age, 3))
    if decision == "fresh":
        s.say_reply(cached, cfg); return
    if decision == "stale":
        spoken = cached + " Это сохранённые данные. Обновляю данные, сэр."
        # Fetch concurrently while the dated snapshot is being read.
        s.ask_server(text, cfg, ctx.trig, ctx.test, ack=spoken, kind="status"); return
    s.ask_server(text if field else "статус по задачам", cfg, ctx.trig, ctx.test, ack=s.pick(cfg, "ack_status"), kind="status")


@handles("tasks")
def tasks(ctx: CommandContext, al: Alias) -> None:
    """Briefing / what is left / all tasks / Notion: from a fresh snapshot, otherwise from the server."""
    s, cfg, mode = ctx.services, ctx.cfg, al["mode"]
    cache, fresh, stamp = s.status.tasks_snapshot(cfg)
    reply, server_text = TASKS.answer(mode, cache if isinstance(cache, dict) else None, fresh, stamp=stamp)
    log.info("tasks %s -> %s", mode, "cache" if reply else "server")
    if reply: s.say_reply(reply, cfg); return
    s.ask_server(server_text, cfg, ctx.trig, ctx.test, ack=s.pick(cfg, "ack_lookup"), kind="free", extra_payload={"intent": "tasks_" + mode})


@handles("time")
def time_now(ctx: CommandContext, al: Alias) -> None:
    now = datetime.datetime.now()
    ctx.services.say(f"Сейчас {JT.time_words(now.hour, now.minute)}, сэр.", ctx.cfg)


@handles("workout")
def workout(ctx: CommandContext, al: Alias) -> None:
    ctx.services.say(workout_summary(ctx.cfg), ctx.cfg)
