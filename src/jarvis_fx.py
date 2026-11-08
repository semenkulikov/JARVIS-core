# "AI butler" post-processing chain (numpy/scipy). All params configurable via cfg["fx"].
import numpy as np
from scipy import signal

FX_DEFAULTS = {
    "enabled": True,
    "pitch": 0.95,          # <1 lowers pitch (resample; also slows by same factor, compensated by faster TTS rate)
    "ring_hz": 45.0, "ring_mix": 0.10,        # subtle metallic ring-mod layer
    "flanger_ms": 2.5, "flanger_depth_ms": 0.8, "flanger_rate": 0.25, "flanger_mix": 0.25,
    "reverb_s": 0.22, "reverb_mix": 0.10,     # short room
    "shelf_hz": 3500, "shelf_db": 2.5,        # gentle presence / air
    "lowcut_hz": 70,
}

def _shelf(x, sr, f, db):
    # high-shelf via parallel highpassed component
    if abs(db) < 0.1: return x
    b, a = signal.butter(2, f / (sr / 2), "high")
    g = 10 ** (db / 20) - 1
    return x + g * signal.lfilter(b, a, x)

def apply(x, sr, p=None):
    c = dict(FX_DEFAULTS); c.update(p or {})
    if not c.get("enabled", True) or len(x) == 0: return x.astype(np.float32), sr
    x = x.astype(np.float64)
    # pitch down by resampling and reinterpreting at the original sr
    if c["pitch"] and abs(c["pitch"] - 1) > 1e-3:
        n = int(len(x) / c["pitch"])
        x = signal.resample_poly(x, n, len(x)) if len(x) < 2_000_000 else signal.resample(x, n)
    t = np.arange(len(x)) / sr
    # ring modulation layer
    if c["ring_mix"] > 0:
        x = (1 - c["ring_mix"]) * x + c["ring_mix"] * x * np.sin(2 * np.pi * c["ring_hz"] * t) * 1.6
    # flanger (short modulated delay)
    if c["flanger_mix"] > 0:
        d = (c["flanger_ms"] + c["flanger_depth_ms"] * np.sin(2 * np.pi * c["flanger_rate"] * t)) * sr / 1000
        idx = np.arange(len(x)) - d
        i0 = np.clip(np.floor(idx).astype(int), 0, len(x) - 1); fr = idx - np.floor(idx)
        i1 = np.clip(i0 + 1, 0, len(x) - 1)
        delayed = (1 - fr) * x[i0] + fr * x[i1]
        x = x + c["flanger_mix"] * delayed
    # short reverb: exponentially decaying noise IR
    if c["reverb_mix"] > 0:
        L = int(c["reverb_s"] * sr); rng = np.random.default_rng(7)
        ir = rng.standard_normal(L) * np.exp(-np.linspace(0, 7, L)); ir /= np.sqrt(np.sum(ir ** 2))
        wet = signal.fftconvolve(x, ir)[:len(x)]
        x = x + c["reverb_mix"] * wet
    x = _shelf(x, sr, c["shelf_hz"], c["shelf_db"])
    if c["lowcut_hz"]:
        b, a = signal.butter(2, c["lowcut_hz"] / (sr / 2), "high"); x = signal.lfilter(b, a, x)
    pk = np.max(np.abs(x)) or 1
    x = x / pk * 0.89
    return x.astype(np.float32), sr
