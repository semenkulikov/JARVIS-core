"""Optional owner-voice check on the audio that ends at the wake word (off by default).

Not authentication: it lowers the chance that a recording or another person runs a command.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import numpy as np

import jarvis_speaker as SPEAKER
from jarvis.adapters.audio import SR, ring_audio

Config = dict[str, Any]
Ring = Iterable[tuple[int, np.ndarray]]
log = logging.getLogger("jarvis")


class SpeakerGate:
    def __init__(self, home: str) -> None:
        self.home = home
        self.verifier: Any = None   # jarvis_speaker.SpeakerVerifier, created on first use

    def check(self, ring: Ring, end: int, cfg: Config) -> tuple[bool, float | None]:
        """(ok, score) of the owner-voice check on the audio that ends at the wake word; (True, None) when off."""
        if not cfg.get("speaker_verify_enabled"): return True, None
        if self.verifier is None: self.verifier = SPEAKER.SpeakerVerifier(self.home, cfg)
        v = self.verifier
        v.cfg = cfg
        win = int(float(v.setting("speaker_window_s")) * SR)
        ok, score = v.check(ring_audio(ring, end - win, end))
        if score is not None: log.info("speaker %s score=%.3f threshold=%.3f", "OK" if ok else "REJECTED", score, v.threshold())
        return bool(ok), score

    def ok(self, ring: Ring, end: int, cfg: Config) -> bool:
        """Optional owner-voice check (off by default): True unless the profile rejects the voice."""
        return self.check(ring, end, cfg)[0]

    def owner_confirmed(self, ring: Ring, end: int, cfg: Config) -> bool:
        """Stricter than ok(): only True when verification is on and actually scored the owner's voice."""
        ok, score = self.check(ring, end, cfg)
        return bool(ok and score is not None)

    def preload(self, cfg: Config) -> None:
        """Load the voice profile at startup so the log shows whether owner verification is active."""
        if not cfg.get("speaker_verify_enabled"): log.info("speaker verify off"); return
        v: Any = SPEAKER.SpeakerVerifier(self.home, cfg); self.verifier = v
        if v.ready(): log.info("speaker verify active threshold=%.3f profile_clips=%s", v.threshold(), v.profile.get("count"))
