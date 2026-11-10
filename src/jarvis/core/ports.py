"""Ports: the interfaces the application needs from the outside world.

Adapters in :mod:`jarvis.adapters` implement them; tests substitute small fakes.
"""
from __future__ import annotations

from typing import Any, Protocol

import numpy as np

Config = dict[str, Any]
Audio = np.ndarray


class SpeechOutput(Protocol):
    """Speaks text; returns False when interrupted or nothing was played."""

    def say(self, text: str, cfg: Config, role: str = "reply", private: bool = False) -> bool: ...


class Synthesizer(Protocol):
    def get_audio(self, text: str, cfg: Config) -> tuple[Audio, int]: ...


class PhraseRecognizer(Protocol):
    """Records one phrase from a capture queue: (text, average confidence, grammar text)."""

    def capture(self, cap: Any, cfg: Config, nospeech_s: float, skip_s: float = 0.0, max_s: float | None = None,
                wake_pause_s: float | None = None) -> tuple[str, float, str]: ...


class ServerTransport(Protocol):
    """Delivers one request to the user's server; replies arrive later through the outbox."""

    def call(self, rid: str, text: str, trigger: str, cfg: Config, test: bool, listener_ack: str = "",
             kind: str = "free", trace: Any = None, extra_payload: dict[str, Any] | None = None) -> bool: ...


class StatusSource(Protocol):
    """Read-only access to the status snapshot the server writes (cache/status.json)."""

    def cached_status(self, field: str | None, cfg: Config) -> tuple[str, str, float | None]: ...

    def load(self) -> dict[str, Any] | None: ...
