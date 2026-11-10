"""Action -> handler table. A new command is a new module in jarvis.commands with @handles(...).

Modules are discovered by load_builtin(); nothing in the listener loop changes for a new command.
The spoken catalogue (examples, «что ты умеешь») stays in jarvis_registry.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Callable

from jarvis.commands.base import Alias, CommandContext, Handler

log = logging.getLogger("jarvis")
HANDLERS: dict[str, Handler] = {}
INFRASTRUCTURE = frozenset({"base", "registry"})
DEFAULT_ACTION = "say"


def handles(*actions: str) -> Callable[[Handler], Handler]:
    """Register the decorated function for the given alias actions; an action has one owner."""
    def register(fn: Handler) -> Handler:
        for act in actions:
            owner = HANDLERS.get(act)
            if owner is not None and owner is not fn:
                raise ValueError(f"action {act!r} already handled by {owner.__module__}.{owner.__name__}")
            HANDLERS[act] = fn
        return fn
    return register


def load_builtin() -> dict[str, Handler]:
    """Import every handler module of this package (idempotent) and return the table."""
    import jarvis.commands as pkg
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name not in INFRASTRUCTURE:
            importlib.import_module(f"{pkg.__name__}.{info.name}")
    return HANDLERS


def dispatch(ctx: CommandContext, al: Alias) -> None:
    act = al.get("action", DEFAULT_ACTION)
    log.info("ALIAS %s (%s) <- %r", al.get("name", "?"), act, ctx.text)
    handler = HANDLERS.get(act) or HANDLERS[DEFAULT_ACTION]
    handler(ctx, al)
