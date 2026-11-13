"""What a command handler gets: the turn (CommandContext) and the services it may use (Services)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol

from jarvis.core.phrases import Picker
from jarvis.core.ports import Config, Laptop
from jarvis.core.state import ListenerState

if TYPE_CHECKING:
    from jarvis.commands.controller import Controller

Alias = dict[str, Any]


class StatusReader(Protocol):
    def cached_status(self, field: str | None, cfg: Config) -> tuple[str, str, float | None]: ...
    def tasks_snapshot(self, cfg: Config) -> tuple[Any, bool, str]: ...
    def github_url(self) -> str | None: ...


class Services(Protocol):
    """Port the conversation implements for command handlers; tests pass a fake."""

    @property
    def state(self) -> ListenerState: ...
    @property
    def status(self) -> StatusReader: ...
    @property
    def picker(self) -> Picker: ...

    def say(self, text: str, cfg: Config, role: str = "reply", private: bool = False) -> bool: ...
    def say_reply(self, text: str, cfg: Config, private: bool = False) -> None: ...
    def ask_server(self, text: str, cfg: Config, trig: str, test: bool, ack: str | None = None,
                   listener_ack: str | None = None, kind: str | None = None, extra_payload: dict[str, Any] | None = None) -> None: ...
    def stop_reply(self) -> None: ...      # cancel the server reply «стоп» cut
    def pick(self, cfg: Config, key: str) -> str: ...
    def controller(self) -> Controller: ...
    def laptop(self) -> Laptop: ...
    def sleep(self) -> Any: ...           # jarvis.adapters.sleep_store.SleepState
    def proactive(self) -> Any: ...       # jarvis.adapters.proactive.Manager


@dataclass(frozen=True)
class CommandContext:
    """One recognised phrase routed to a command."""

    text: str
    cfg: Config
    trig: str
    test: bool
    services: Services

    def ack(self, al: Alias) -> None:
        """Short spoken confirmation: the alias reply, otherwise a varied «done» phrase."""
        s = self.services
        s.say(al.get("reply") or s.pick(self.cfg, "ack_command"), self.cfg, role="ack")


Handler = Callable[[CommandContext, Alias], None]
