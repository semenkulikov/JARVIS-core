"""Commands of jarvis_commands.Controller (quick2) and aliases forwarded to the server (webhook)."""
from __future__ import annotations

from typing import Any, Callable

import jarvis_dialog as DIALOG
from jarvis.commands.base import Alias, CommandContext
from jarvis.commands.registry import handles


@handles("quick2")
def quick(ctx: CommandContext, al: Alias) -> None:
    s, cfg = ctx.services, ctx.cfg
    key = DIALOG.ack_key(al); spoken = s.pick(cfg, key) if key else ""
    # After an instant ack a server fallback must not add a second one.
    fwd_ack: dict[str, Any] = {"ack": "", "listener_ack": spoken} if spoken else {}

    def fallback(value: str, **kw: Any) -> None:
        s.ask_server(value, cfg, ctx.trig, ctx.test, **{**fwd_ack, **kw})

    def run(speak: Callable[..., Any]) -> Any:
        st = s.state
        return s.controller().execute(al, ctx.text, cfg, speak, fallback, last_reply=st.last_reply, last_private=st.last_reply_private,
                                      trigger=ctx.trig, confidence=st.last_input_conf, test=ctx.test)

    keep = DIALOG.ack_then(s.say, cfg, spoken, run)
    if not keep: s.state.followup_eligible = False


@handles("webhook")
def webhook(ctx: CommandContext, al: Alias) -> None:
    ctx.services.ask_server(al.get("target") or ctx.text, ctx.cfg, ctx.trig, ctx.test, ack=al.get("reply") or None)
