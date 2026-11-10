"""Optional owner-voice check on the audio that ends at the wake word (off by default).

Not authentication: it lowers the chance that a recording or another person runs a command.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple

import numpy as np

from jarvis.adapters.audio import SR, ring_audio
from jarvis.core.voiceprint import DEFAULTS, PROFILE_VERSION, cosine, fbank

Config = dict[str, Any]
Ring = Iterable[tuple[int, np.ndarray]]
log = logging.getLogger("jarvis")


def file_sha256(path: os.PathLike[str] | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class SpeakerVerifier:
    """Lazy model + profile; ``check`` never raises and fails open when not ready."""

    def __init__(self, home: os.PathLike[str] | str, cfg: Mapping[str, Any],
                 session_factory: Callable[[Path], Any] | None = None) -> None:
        self.home = Path(home)
        self.cfg = cfg
        self._factory = session_factory
        self._session: Any = None
        self.profile: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None

    def setting(self, key: str) -> Any:
        return self.cfg.get(key, DEFAULTS[key])

    def _path(self, key: str) -> Path:
        p = Path(str(self.setting(key)))
        return p if p.is_absolute() else self.home / p

    def ready(self) -> bool:
        if self._session is not None and self.profile is not None:
            return True
        if self.error:
            return False
        try:
            profile = json.loads(self._path("speaker_profile").read_text(encoding="utf-8"))
            self.profile = profile if isinstance(profile, dict) else {}
            if self.profile.get("version") != PROFILE_VERSION or len(self.profile.get("centroid") or []) == 0:
                raise ValueError("profile_invalid")
            self._session = (self._factory or _onnx_session)(self._path("speaker_model"))
            return True
        except Exception as e:  # missing profile/model: verification is skipped, logged once
            self.error = type(e).__name__
            log.warning("speaker verification unavailable (%s); not filtering", self.error)
            return False

    def embed(self, audio: np.ndarray) -> np.ndarray:
        feats = fbank(audio)[None, :, :]
        if self._session is None:
            self._session = (self._factory or _onnx_session)(self._path("speaker_model"))
        name = self._session.get_inputs()[0].name
        return np.asarray(self._session.run(None, {name: feats})[0][0], dtype=np.float32)

    def threshold(self) -> float:
        value = self.setting("speaker_threshold")
        return float(value if value is not None else (self.profile or {}).get("threshold", 0.5))

    def check(self, audio: np.ndarray) -> Tuple[bool, Optional[float]]:
        """(accepted, score). Disabled / not ready / too short -> (True, None)."""
        if not self.setting("speaker_verify_enabled") or not self.ready():
            return True, None
        if len(audio) < float(self.setting("speaker_min_audio_s")) * SR:
            return True, None
        try:
            score = cosine(self.embed(audio), np.asarray((self.profile or {})["centroid"], dtype=np.float32))
        except Exception as e:
            log.warning("speaker scoring failed (%s); not filtering", type(e).__name__)
            return True, None
        return (score >= self.threshold()), round(score, 3)


def _onnx_session(path: Path) -> Any:
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


class SpeakerGate:
    def __init__(self, home: str) -> None:
        self.home = home
        self.verifier: SpeakerVerifier | None = None   # created on first use

    def check(self, ring: Ring, end: int, cfg: Config) -> tuple[bool, float | None]:
        """(ok, score) of the owner-voice check on the audio that ends at the wake word; (True, None) when off."""
        if not cfg.get("speaker_verify_enabled"): return True, None
        if self.verifier is None: self.verifier = SpeakerVerifier(self.home, cfg)
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
        v: Any = SpeakerVerifier(self.home, cfg); self.verifier = v
        if v.ready(): log.info("speaker verify active threshold=%.3f profile_clips=%s", v.threshold(), v.profile.get("count"))
