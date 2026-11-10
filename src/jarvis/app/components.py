"""Every long-lived object of the listener, wired once by jarvis.app.context.build_app()."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.adapters.asr_vosk import VoskASR
from jarvis.adapters.audio import MicInput
from jarvis.adapters.outbox import Outbox
from jarvis.adapters.speaker import SpeakerGate
from jarvis.adapters.status_cache import StatusCache
from jarvis.adapters.transport import WebhookTransport
from jarvis.adapters.tts import Voice
from jarvis.core.config import ConfigStore
from jarvis.core.lazy import Lazy
from jarvis.core.phrases import Picker
from jarvis.core.routing import Router
from jarvis.core.state import ListenerFSM, ListenerState, RequestLedger, Signals


@dataclass(frozen=True)
class Paths:
    """Files under JARVIS_HOME the listener reads or writes."""

    home: str

    @classmethod
    def of(cls, home: str | Path) -> Paths:
        return cls(str(home))

    def at(self, *parts: str) -> str:
        return os.path.join(self.home, *parts)

    @property
    def stop_file(self) -> str: return self.at("stop")
    @property
    def test_trigger(self) -> str: return self.at("test_trigger")
    @property
    def test_bargein(self) -> str: return self.at("test_bargein")
    @property
    def cache(self) -> str: return self.at("cache")
    @property
    def models(self) -> str: return self.at("models")


@dataclass
class Components:
    paths: Paths
    config: ConfigStore
    picker: Picker
    signals: Signals
    fsm: ListenerFSM
    state: ListenerState
    ledger: RequestLedger
    router: Router
    mic: MicInput
    asr: VoskASR
    speaker: SpeakerGate
    transport: WebhookTransport
    player: Any                 # jarvis_audio.Player
    voice: Voice
    outbox: Outbox
    status: StatusCache
    controller: Lazy[Any]       # jarvis_commands.Controller
    sleep: Lazy[Any]            # jarvis_sleep.SleepState
    proactive: Lazy[Any]        # jarvis_proactive.Manager
