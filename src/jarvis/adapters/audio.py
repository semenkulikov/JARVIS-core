"""Microphone input and audio helpers: capture queue, levels, gain, clap detection, ring buffer."""
from __future__ import annotations

import logging
import queue
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

SR = 16000
CHUNK = 1280  # 80 ms, openWakeWord frame
log = logging.getLogger("jarvis")


@dataclass
class MicLevels:
    max: float = 0.0
    sum: float = 0.0
    n: int = 0

    def add(self, x: np.ndarray) -> None:
        self.max = max(self.max, float(np.abs(x).max())); self.sum += float(np.sqrt(np.mean(x * x))); self.n += 1

    def report(self) -> None:
        """Log peak and average since the last report, then start over."""
        n = max(self.n, 1)
        log.info("mic level: peak=%.3f avg_rms=%.4f chunks=%d", self.max, self.sum / n, self.n)
        self.max, self.sum, self.n = 0.0, 0.0, 0


class MicInput:
    """PortAudio callback side: frames go to a bounded queue; when it is full they are dropped."""

    def __init__(self, maxsize: int = 1000) -> None:
        self.queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=maxsize)
        self.levels = MicLevels()

    def callback(self, indata: np.ndarray, frames: int, t: Any, status: Any) -> None:
        try: self.queue.put_nowait(indata[:, 0].copy())
        except queue.Full: pass

    def open(self, sd: Any, device: int | None) -> Any:
        return sd.InputStream(device=device, samplerate=SR, channels=1, dtype="float32", blocksize=CHUNK, callback=self.callback)


class Capture:
    """Frames for one phrase, starting with the audio buffered before the wake word."""

    def __init__(self, pre: Iterable[np.ndarray] | None = None) -> None:
        pre = list(pre or [])
        self.q: queue.Queue[np.ndarray] = queue.Queue()
        self.audio_start = time.time() - sum(len(x) for x in pre) / SR
        for x in pre: self.q.put(x)


class AGC:
    """Automatic gain for the recognizer: quiet speech is lifted towards a target peak."""

    def __init__(self, cfg: Mapping[str, Any]) -> None:
        self.env = 0.05; self.max_g = float(cfg.get("vosk_agc_max_gain", 12)); self.tgt = float(cfg.get("vosk_agc_target_peak", 0.6))
        self.on = bool(cfg.get("vosk_agc", True)); self.gains: list[float] = []

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if not self.on: return x
        pk = float(np.abs(x).max()); self.env = max(pk, self.env * 0.97, 0.02)
        g = min(self.max_g, self.tgt / self.env); self.gains.append(g)
        return np.clip(x * g, -1, 1)


def clip_level(x: np.ndarray) -> tuple[float, float]:
    """(peak, RMS) of a float clip; (0, 0) for an empty one."""
    if not len(x): return 0.0, 0.0
    return float(np.abs(x).max()), float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def normalize_clip(x: np.ndarray, target_peak: float, max_gain: float) -> tuple[np.ndarray, float]:
    """One gain for the whole clip towards ``target_peak`` (at most ``max_gain``, never below 1, never clipping)."""
    peak = clip_level(x)[0]
    if peak <= 1e-6: return x, 1.0
    gain = max(1.0, min(float(max_gain), min(float(target_peak), 0.99) / peak))
    return (x * gain).astype(np.float32), gain


def ring_audio(ring: Iterable[tuple[int, np.ndarray]], a: int, b: int) -> np.ndarray:
    """Samples [a, b) from the ring buffer of (start_pos, chunk)."""
    parts = []
    for p, c in ring:
        lo, hi = max(a, p), min(b, p + len(c))
        if hi > lo: parts.append(c[lo - p:hi - p])
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def frames_after(ring: Sequence[tuple[int, np.ndarray]], start: int) -> list[np.ndarray]:
    """Buffered chunks that end after sample ``start`` (the audio before a wake word)."""
    return [c for (p, c) in ring if p + len(c) > start]


def pick_device(sd: Any, cfg: Mapping[str, Any]) -> int | None:
    """Input device whose name matches ``mic_name_contains``, preferring WASAPI; None for the default."""
    keys = [k.lower() for k in cfg.get("mic_name_contains", ["Intel", "Smart Sound", "массив", "Microphone Array"])]
    devs = sd.query_devices(); apis = sd.query_hostapis(); cands: list[tuple[int, int, str, str]] = []
    for i, d in enumerate(devs):
        if d["max_input_channels"] < 1: continue
        n = d["name"].lower()
        if any(k in n for k in keys):
            api = apis[d["hostapi"]]["name"]
            cands.append(({"Windows WASAPI": 0, "MME": 1, "Windows DirectSound": 2}.get(api, 3), i, d["name"], api))
    for _rank, i, name, api in sorted(cands):
        try:
            sd.check_input_settings(device=i, samplerate=SR, channels=1, dtype="float32")
            log.info("mic selected: [%d] %s (%s)", i, name, api); return i
        except Exception as e:
            log.info("mic %d %s (%s) rejected: %s", i, name, api, e)
    log.warning("no matching mic, using default"); return None


class ClapDetector:
    """Clap = sharp onset (attack) + loud vs background + fast decay. Two claps, isolated, 0.12-0.9 s apart.
    Reverb tails / bounces right after a clap are ignored (clap_tail_s); weak noise (< clap_noise_rel * clap peak) is ignored."""
    def __init__(self) -> None:
        self.bg = 0.002; self.prev_r = 0.0; self.cur: dict[str, Any] | None = None; self.events: list[dict[str, Any]] = []; self.last_log = 0.0; self.last_clap_t = -9.0; self.last_noise_t = -9.0
    def feed(self, x: np.ndarray, pos: int, c: Mapping[str, Any]) -> bool:
        fl = 160
        for i in range(0, len(x) - fl + 1, fl):
            f = x[i:i + fl]; r = float(np.sqrt(np.mean(f * f))); pk = float(np.abs(f).max()); t = (pos + i) / SR
            if self.cur is None:
                att = r / max(self.prev_r, 1e-5)
                in_tail = t - self.last_clap_t < c["clap_tail_s"]
                if pk >= c["clap_min_peak"] and r >= c["clap_ratio"] * self.bg and att >= c["clap_attack"]:
                    self.cur = {"t": t, "pk": pk, "r": r, "bg": self.bg, "att": att}
                elif (not in_tail and pk >= c["clap_log_min_peak"] and r >= 4 * self.bg and att >= c["clap_noise_attack"]
                      and t - self.last_noise_t > 0.1):
                    self.events.append({"t": t, "ok": False, "pk": pk, "att": att}); self.last_noise_t = t
                    if t - self.last_log > 0.3:
                        log.info("clap near-miss: peak=%.3f rms=%.4f bg=%.4f attack=%.1f", pk, r, self.bg, att); self.last_log = t
                if r < self.bg: self.bg = 0.9 * self.bg + 0.1 * r
                elif not in_tail: self.bg = 0.998 * self.bg + 0.002 * min(r, 20 * self.bg)
                self.bg = max(self.bg, 1e-4)
            else:
                cu = self.cur; cu["pk"] = max(cu["pk"], pk); cu["r"] = max(cu["r"], r); dur = t - cu["t"]
                if r < cu["r"] * c["clap_decay"] or dur > c["clap_max_len_s"]:
                    ok = dur <= c["clap_max_len_s"]
                    log.info("clap candidate: peak=%.3f rms=%.4f bg=%.4f attack=%.1f dur=%.3f -> %s", cu["pk"], cu["r"], cu["bg"], cu["att"], dur, "ok" if ok else "too long")
                    self.events.append({"t": cu["t"], "ok": ok, "pk": cu["pk"], "att": cu["att"]}); self.cur = None
                    self.last_clap_t = t
            self.prev_r = r
        now_t = (pos + len(x)) / SR
        if self.cur is None and self.events and now_t - self.events[-1]["t"] >= c["clap_quiet_s"]:
            cl = [self.events[-1]]
            for e in reversed(self.events[:-1]):
                if cl[0]["t"] - e["t"] < max(c["clap_quiet_s"], c["clap_gap_max_s"]): cl.insert(0, e)
                else: break
            self.events = []
            oks = [e for e in cl if e["ok"]]
            if not oks: return False
            ref = max(e["pk"] for e in oks)
            sig = [e for e in cl if e["ok"] or e["pk"] >= c["clap_noise_rel"] * ref]
            desc = ", ".join(f"{e['t'] - cl[0]['t']:+.2f}s pk={e['pk']:.2f} att={e['att']:.0f}{'*' if e['ok'] else ''}" for e in cl)
            if len(sig) == 2 and all(e["ok"] for e in sig):
                g = sig[1]["t"] - sig[0]["t"]; sim = max(sig[0]["pk"], sig[1]["pk"]) / max(min(sig[0]["pk"], sig[1]["pk"]), 1e-4)
                if c["clap_gap_min_s"] <= g <= c["clap_gap_max_s"] and sim <= c["clap_peak_similarity"]:
                    log.info("DOUBLE CLAP gap=%.2f sim=%.1f [%s]", g, sim, desc); return True
                log.info("clap pair rejected: gap=%.2f sim=%.1f [%s]", g, sim, desc)
            else:
                log.info("clap cluster rejected: %d significant (%d clap-like) [%s]", len(sig), len(oks), desc)
        return False
