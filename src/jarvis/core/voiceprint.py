"""Voiceprint math for the optional owner-voice check: fbank features, cosine, profile and threshold.

Off by default (``speaker_verify_enabled``). Uses the WeSpeaker ResNet34 ONNX model
(26.5 MB, 256-d embeddings) through onnxruntime, which openWakeWord already needs, and a
NumPy Kaldi-compatible fbank frontend, so no extra Python packages are required.
Enrollment: ``scripts/enroll_speaker.py`` writes ``<home>/speaker/profile.json``.
The model session and verifier live in jarvis.adapters.speaker.
"""
from __future__ import annotations

import time
from typing import Any, Optional, Sequence

import numpy as np

SR = 16000
MODEL_NAME = "voxceleb_resnet34_LM.onnx"
MODEL_URL = "https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM/resolve/main/" + MODEL_NAME
MODEL_SHA256 = "7bb2f06e9df17cdf1ef14ee8a15ab08ed28e8d0ef5054ee135741560df2ec068"
PROFILE_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "speaker_verify_enabled": False,
    "speaker_model": "models/speaker/" + MODEL_NAME,
    "speaker_profile": "speaker/profile.json",
    "speaker_threshold": None,      # None -> threshold stored in the profile
    "speaker_window_s": 2.0,        # audio ending at the wake word that is compared
    "speaker_min_audio_s": 0.8,     # shorter clips cannot be judged -> allowed
}


# ------------------------------------------------------------------ frontend
def _mel_banks(n_fft: int, n_mels: int, sr: int, low: float = 20.0, high: Optional[float] = None) -> np.ndarray:
    high = high or sr / 2.0

    def mel(f: Any) -> np.ndarray: return np.asarray(1127.0 * np.log(1.0 + np.asarray(f) / 700.0))
    lo, hi = mel(low), mel(high)
    centers = np.linspace(lo, hi, n_mels + 2)
    bins = mel(np.arange(n_fft // 2) * sr / n_fft)
    banks = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(n_mels):
        left, c, right = centers[m], centers[m + 1], centers[m + 2]
        up = (bins - left) / (c - left)
        down = (right - bins) / (right - c)
        banks[m, : n_fft // 2] = np.maximum(0.0, np.minimum(up, down))
    return banks


_BANKS: dict[tuple[int, int, int], np.ndarray] = {}


def fbank(wave: np.ndarray, sr: int = SR, n_mels: int = 80) -> np.ndarray:
    """Kaldi-style log mel fbank (25 ms hamming / 10 ms, preemph 0.97, no dither), CMN applied."""
    x = np.asarray(wave, dtype=np.float64) * 32768.0  # WeSpeaker feeds int16-scaled samples
    flen, shift, n_fft = int(0.025 * sr), int(0.010 * sr), 512
    if len(x) < flen:
        return np.zeros((0, n_mels), dtype=np.float32)
    n = 1 + (len(x) - flen) // shift
    idx = np.arange(flen)[None, :] + shift * np.arange(n)[:, None]
    frames = x[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1] * (1 - 0.97), frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    frames = frames * np.hamming(flen)[None, :]
    spec = np.abs(np.fft.rfft(frames, n=n_fft, axis=1)) ** 2
    key = (n_fft, n_mels, sr)
    if key not in _BANKS:
        _BANKS[key] = _mel_banks(n_fft, n_mels, sr)
    feats = np.log(np.maximum(spec @ _BANKS[key].T, np.finfo(np.float32).eps))
    feats = feats - feats.mean(axis=0, keepdims=True)
    return np.asarray(feats, dtype=np.float32)


def trim_silence(audio: np.ndarray, rel: float = 0.1, frame: int = 320) -> np.ndarray:
    """Drop leading/trailing frames quieter than ``rel`` of the loudest frame."""
    a = np.asarray(audio, dtype=np.float32)
    n = len(a) // frame
    if n == 0:
        return a
    rms = np.sqrt(np.mean(a[: n * frame].reshape(n, frame) ** 2, axis=1))
    loud = np.nonzero(rms >= rel * float(rms.max()))[0] if rms.max() > 0 else np.zeros(0, np.int64)
    if len(loud) == 0:
        return a[:0]
    return a[loud[0] * frame:(loud[-1] + 1) * frame]


# ------------------------------------------------------------------ scoring
def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else 0.0


def centroid(embeddings: Sequence[np.ndarray]) -> np.ndarray:
    unit = [e / max(np.linalg.norm(e), 1e-9) for e in embeddings]
    return np.mean(unit, axis=0)


def suggest_threshold(embeddings: Sequence[np.ndarray]) -> float:
    """Leave-one-out owner scores minus a safety margin, clamped to a sane range."""
    if len(embeddings) < 2:
        return 0.5
    scores = []
    for i, e in enumerate(embeddings):
        rest = [x for j, x in enumerate(embeddings) if j != i]
        scores.append(cosine(e, centroid(rest)))
    mu, sd = float(np.mean(scores)), float(np.std(scores))
    return round(min(0.6, max(0.35, mu - max(0.1, 3 * sd))), 3)


def make_profile(embeddings: Sequence[np.ndarray], model_sha256: str = MODEL_SHA256) -> dict[str, Any]:
    return {"version": PROFILE_VERSION, "model_sha256": model_sha256, "created": time.time(),
            "threshold": suggest_threshold(embeddings), "centroid": centroid(embeddings).round(6).tolist(),
            "count": len(embeddings)}
