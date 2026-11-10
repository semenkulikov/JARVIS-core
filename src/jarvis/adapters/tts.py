"""Speech output: Silero or Piper synthesis, the WAV phrase cache and chunked playback.

The next sentence is synthesized while the current one plays; playback stops at once when the
interrupt signal is set.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
import wave
from typing import Any

import numpy as np

import jarvis_text as JT
from jarvis.adapters.audio import SR
from jarvis.core.state import ListenerFSM, ListenerState, Mode, Signals

Config = dict[str, Any]
Chunk = tuple[np.ndarray, int]
log = logging.getLogger("jarvis")


def _xml_escape(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wav_write(p: str, a: np.ndarray, sr: int) -> None:
    tmp = p + "." + uuid.uuid4().hex + ".tmp"
    try:
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp): os.remove(tmp)


def _wav_read(p: str) -> tuple[np.ndarray, int]:
    with wave.open(p, "rb") as w:
        sr = w.getframerate(); d = w.readframes(w.getnframes())
    return np.frombuffer(d, dtype=np.int16).astype(np.float32) / 32767, sr


def split_text(text: str, limit: int = 170) -> list[str]:
    """Sentences no longer than ``limit``, split at commas and then at spaces when needed."""
    out = []
    for sent in re.split(r"(?<=[.!?…])\s+|\n+", text):
        sent = sent.strip()
        if not sent: continue
        if len(sent) <= limit: out.append(sent); continue
        cur = ""
        for piece in re.split(r"(?<=[,;:])\s+", sent):
            if cur and len(cur) + len(piece) + 1 > limit: out.append(cur); cur = piece
            else: cur = (cur + " " + piece).strip()
        if cur: out.append(cur)
    # Preserve sentence boundaries, especially the very first short sentence.
    # Bound even punctuation-free text by word boundaries.
    bounded = []
    for item in out:
        while len(item) > limit:
            cut = item.rfind(" ", 0, limit + 1)
            if cut <= 0: cut = limit
            bounded.append(item[:cut].strip()); item = item[cut:].strip()
        if item: bounded.append(item)
    return bounded


class Voice:
    """Implements :class:`jarvis.core.ports.SpeechOutput` and :class:`~jarvis.core.ports.Synthesizer`."""

    def __init__(self, home: str, state: ListenerState, signals: Signals, fsm: ListenerFSM, player: Any) -> None:
        self.home, self.state, self.signals, self.fsm, self.player = home, state, signals, fsm, player
        self._engines: dict[str, Any] = {}
        self._syn_lock = threading.Lock()

    def _cache_path(self, text: str, cfg: Config, ext: str) -> str:
        sig = json.dumps(["v3.8-stress2", JT.accent_state(), cfg.get("tts_engine"), cfg.get("silero_model"), cfg.get("stress_dict"), cfg.get("phrase_rewrites"),
                          cfg.get("fx"), cfg.get("silero_speaker"), cfg.get("silero_rate"), cfg.get("piper_voice"), text], ensure_ascii=False)
        cdir = os.path.join(self.home, "cache", "tts"); os.makedirs(cdir, exist_ok=True)
        return os.path.join(cdir, hashlib.md5(sig.encode("utf-8")).hexdigest() + ext)

    def _silero_model(self, cfg: Config) -> Any:
        import torch
        if "silero_thr" not in self._engines:
            torch.set_num_threads(int(cfg.get("tts_threads", 3))); self._engines["silero_thr"] = 1
        mid = cfg.get("silero_model", "v5_6_ru")
        if self._engines.get("silero_id") != mid:
            p = os.path.join(self.home, "models", "silero", mid + ".pt")
            self._engines["silero"] = torch.package.PackageImporter(p).load_pickle("tts_models", "model"); self._engines["silero_id"] = mid
        return self._engines["silero"]

    def synth_local(self, text: str, cfg: Config) -> tuple[np.ndarray, int]:
        with self._syn_lock:
            return self._synth_local(text, cfg)

    def _synth_local(self, text: str, cfg: Config) -> tuple[np.ndarray, int]:
        e = cfg.get("tts_engine", "silero")
        if e == "silero":
            m = self._silero_model(cfg)
            kw = dict(speaker=cfg.get("silero_speaker", "eugene"), sample_rate=48000, put_accent=True, put_yo=True)
            if str(self._engines.get("silero_id", "")).startswith("v5"): kw.update(put_stress_homo=True, put_yo_homo=True)
            rate = cfg.get("silero_rate", "fast")
            def one(t: str) -> Any:
                try:
                    return m.apply_tts(ssml_text=f'<speak><prosody rate="{rate}">{_xml_escape(t)}</prosody></speak>', **kw)
                except Exception as ex:
                    log.info("silero ssml failed (%s), plain text", type(ex).__name__ if cfg.get("private_tts") else ex)
                    return m.apply_tts(text=t[:900], **kw)
            try:
                return one(text).numpy().astype(np.float32), 48000
            except Exception as ex:
                log.warning("silero failed on chunk (%s), per-sentence fallback", type(ex).__name__ if cfg.get("private_tts") else ex)
            outs: list[np.ndarray] = []
            for p in [x for x in re.split(r'(?<=[.!?…,;:])\s+', text) if x.strip()]:
                try: outs.append(one(p).numpy().astype(np.float32)); outs.append(np.zeros(int(48000 * 0.1), np.float32))
                except Exception as ex2: log.warning("silero skip part %r: %s", "[private clipboard text]" if cfg.get("private_tts") else p[:60], type(ex2).__name__)
            if not outs: raise RuntimeError("silero produced nothing")
            return np.concatenate(outs), 48000
        if e == "piper":
            from piper import PiperVoice, SynthesisConfig
            k = "piper:" + cfg.get("piper_voice", "ruslan")
            if k not in self._engines:
                self._engines[k] = PiperVoice.load(os.path.join(self.home, "models", "piper", f"ru_RU-{cfg.get('piper_voice','ruslan')}-medium.onnx"))
            v = self._engines[k]
            chunks = [c.audio_float_array for c in v.synthesize(text, syn_config=SynthesisConfig(length_scale=float(cfg.get("piper_length_scale", 0.85))))]
            return np.concatenate(chunks).astype(np.float32), v.config.sample_rate
        raise ValueError("unknown engine " + e)

    def get_audio(self, text: str, cfg: Config) -> tuple[np.ndarray, int]:
        cp = self._cache_path(text, cfg, ".wav")
        if os.path.exists(cp): return _wav_read(cp)
        norm = JT.normalize(text, cfg)
        a, sr = self.synth_local(norm, cfg)
        fx = cfg.get("fx", {"enabled": True})
        if fx.get("enabled", True):
            import jarvis_fx
            a, sr = jarvis_fx.apply(a, sr, fx)
        if len(text) <= 240 and not cfg.get("private_tts",False):
            try: _wav_write(cp, a, sr)
            except Exception: pass
        return a, sr

    def say(self, text: str, cfg: Config, role: str = "reply", private: bool = False) -> bool:
        """Speak text; synthesis of the next chunk overlaps playback. Returns False if interrupted/failed."""
        text = (text or "").strip()
        if not text: return True
        log.info("SAY start (%d chars): %s", len(text), "[private clipboard text]" if private else text[:800])
        if self.signals.interrupt.is_set(): return False
        if private: cfg = dict(cfg, private_tts=True)
        chunks = split_text(text, int(cfg.get("tts_chunk_chars", 170)))
        q: queue.Queue[Chunk | None] = queue.Queue(maxsize=2); err: list[Exception] = []; cancelled = threading.Event()
        def enqueue(item: Chunk | None) -> bool:
            while not cancelled.is_set() and not self.signals.interrupt.is_set():
                try: q.put(item, timeout=0.1); return True
                except queue.Full: pass
            return False
        def prod() -> None:
            for ch in chunks:
                if cancelled.is_set() or self.signals.interrupt.is_set(): break
                try:
                    item = self.get_audio(ch, cfg)
                    if not enqueue(item): return
                except Exception as e: err.append(e); log.warning("tts chunk failed: %s", e)
            enqueue(None)
        threading.Thread(target=prod, daemon=True).start()
        self.signals.speaking.set(); played = 0; t0 = time.time(); self.state.speaking_text = text.lower().replace("ё", "е")
        prev_mode = self.fsm.mode; self.fsm.to(Mode.SPEAKING, role)
        try:
            while True:
                if self.signals.interrupt.is_set(): break
                try: item = q.get(timeout=0.1)
                except queue.Empty: continue
                if item is None or self.signals.interrupt.is_set(): break
                a, sr = item
                if played == 0: log.info("tts first chunk ready in %.2fs", time.time() - t0)
                gap = np.zeros(int(sr * float(cfg.get("tts_gap_s", 0.08))), np.float32)
                self.state.perf("first_audio", audio_role=role)
                self.state.perf("first_ack_audio" if role == "ack" else "first_reply_audio")
                self.player.play(np.concatenate([a, gap]), sr, self.signals.interrupt.is_set); played += 1
            if self.signals.interrupt.is_set():
                log.info("speech interrupted after %d/%d chunks", played, len(chunks)); return False
            if played == 0:
                log.warning("TTS produced nothing, chime instead: %s", "[private clipboard text]" if private else text[:200])
                try: self.beep()
                except Exception: pass
                return False
            self.state.last_spoken = text; self.state.last_spoken_end = time.monotonic()
            self.state.speech_serial += 1
            if role == "reply":
                self.state.reply_parts.append(text)
                self.state.last_reply = " ".join(self.state.reply_parts)
                self.state.last_reply_private = private or self.state.last_reply_private if len(self.state.reply_parts)>1 else bool(private)
            log.info("SPOKE(%d chunks): %s", played, "[private clipboard text]" if private else text[:200]); return True
        except Exception as e:
            log.warning("TTS/playback failed (%s)", e); return False
        finally:
            cancelled.set(); self.signals.speaking.clear(); self.state.speaking_text = ""; self.fsm.restore(prev_mode)

    def beep(self) -> None:
        t = np.linspace(0, 0.12, int(SR * 0.12), False)
        self.player.play((0.25 * np.sin(2 * np.pi * 880 * t)).astype(np.float32), SR)
