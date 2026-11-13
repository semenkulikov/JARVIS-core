"""Composition root: the only place that creates and wires the listener's objects."""
from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jarvis.adapters import playback as AUDIO
from jarvis.adapters import fatsecret as FATSECRET
from jarvis.adapters import laptop as LAPTOP
from jarvis.adapters import paths as PATHS
from jarvis.adapters import proactive as PROACTIVE
from jarvis.adapters.accent import Accentizer
from jarvis.adapters.asr_vosk import VoskASR
from jarvis.adapters.food_diary import FatSecretCall, FoodLogger
from jarvis.adapters.audio import MicInput
from jarvis.adapters.outbox import Outbox
from jarvis.adapters.overlay import Overlay
from jarvis.adapters.project_tools import ProjectTools
from jarvis.adapters.sleep_store import SleepState
from jarvis.adapters.speaker import SpeakerGate
from jarvis.adapters.status_cache import StatusCache
from jarvis.adapters.system import SystemBackend
from jarvis.adapters.timers import PersistentTimers
from jarvis.adapters.transport import WebhookTransport
from jarvis.adapters.tts import Voice
from jarvis.app import settings
from jarvis.app.components import Components, Paths
from jarvis.app.conversation import Conversation
from jarvis.app.listener import Listener
from jarvis.app.server_jobs import ServerWorker
from jarvis.app.warmup import Warmup
from jarvis.commands import catalog as CATALOG
from jarvis.commands.controller import Controller
from jarvis.core import cheatsheet as CHEATSHEET
from jarvis.core.lazy import Lazy
from jarvis.core.phrases import Picker
from jarvis.core.ports import Config, DesktopBackend, PhraseRecognizer, ProjectToolsPort, ServerTransport, SpeechOutput, StatusSource, Synthesizer
from jarvis.core.routing import Router
from jarvis.core.state import ListenerFSM, ListenerState, RequestLedger, Signals


@dataclass
class App:
    c: Components
    conversation: Conversation
    warmup: Warmup
    listener: Listener


def build_controller(home: str | Path, backend: DesktopBackend | None = None, clock: Callable[[], float] = time.monotonic,
                     food_call: FatSecretCall | None = None, tools: ProjectToolsPort | None = None) -> Controller:
    """The quick command controller over the real adapters; tests replace the backend, FatSecret or tools."""
    base = Path(home)

    def fatsecret(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return FATSECRET.call(method, params)  # looked up per call, so test guards apply
    call = food_call or fatsecret

    def food(cfg: Config) -> FoodLogger: return FoodLogger(base, call, cfg)
    return Controller(base, backend or SystemBackend(), PersistentTimers(base / "cache" / "timers.json"),
                      tools or ProjectTools(base), food, PATHS.screenshots_dir(base), clock)


def cheatsheet_content(config: Any) -> Callable[[], tuple[list[CHEATSHEET.Section], Config]]:
    """The overlay text, rebuilt from the live config and the command catalogue on every show."""
    catalog = {c.id: (c.summary, c.examples) for c in CATALOG.COMMANDS}
    groups = [(key, title, [c.id for c in cmds]) for (key, _), (title, cmds) in zip(CATALOG.CATEGORIES, CATALOG.by_category(), strict=True)]

    def content() -> tuple[list[CHEATSHEET.Section], Config]:
        cfg = config.load()
        return CHEATSHEET.build(cfg, catalog, groups), cfg
    return content


def build_app(home: str | Path, sd: Any = None) -> App:
    """Wire everything for JARVIS_HOME ``home``; ``sd`` is the sounddevice module (imported when None)."""
    if sd is None: sd = importlib.import_module("sounddevice")
    paths = Paths.of(home)
    os.makedirs(paths.cache, exist_ok=True)
    outbox = Outbox(paths.at("outbox")); outbox.ensure()
    state, signals, fsm, ledger = ListenerState(), Signals(), ListenerFSM(), RequestLedger()
    controller: Lazy[Controller] = Lazy(lambda: build_controller(paths.home))

    def shutdown_pending() -> bool:
        ctl = controller.peek()
        return ctl is not None and bool(getattr(ctl, "pending", None))

    player = AUDIO.Player(sd); accent = Accentizer()
    config = settings.config_store(paths.home); transport = WebhookTransport(signals, ledger)
    c = Components(
        paths=paths, config=config, picker=Picker(settings.DEFAULTS),
        signals=signals, fsm=fsm, state=state, ledger=ledger, router=Router(state, shutdown_pending),
        mic=MicInput(), asr=VoskASR(state), speaker=SpeakerGate(paths.home),
        transport=transport, player=player, accent=accent,
        voice=Voice(paths.home, state, signals, fsm, player, accent),
        outbox=outbox, jobs=ServerWorker(transport, outbox, ledger, lambda: config.load()), status=StatusCache(os.path.join(paths.cache, "status.json")),
        controller=controller, laptop=LAPTOP,
        sleep=Lazy(lambda: SleepState(os.path.join(paths.cache, "sleep.json"))),
        proactive=Lazy(lambda: PROACTIVE.Manager(paths.home)),
        input_volume=SystemBackend().input_volume if os.name == "nt" else (lambda: None),
        overlay=Overlay(cheatsheet_content(config), os.path.join(paths.cache, "overlay.json")),
    )
    conversation = Conversation(c)
    warmup = Warmup(c)
    return App(c, conversation, warmup, Listener(c, conversation, warmup, sd))


def ports_of(c: Components) -> tuple[SpeechOutput, Synthesizer, PhraseRecognizer, ServerTransport, StatusSource]:
    """The wired adapters seen through the core ports; mypy checks that each one implements its port."""
    return c.voice, c.voice, c.asr, c.transport, c.status
