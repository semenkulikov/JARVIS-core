"""Speech recognition with Vosk: phrase capture with a grammar hint, free transcripts, wake checks."""
from __future__ import annotations

import json
import logging
import queue
import time
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from jarvis.core import gate as GATE
from jarvis.core import names as NAMES
from jarvis.adapters.audio import AGC, CHUNK, SR, Capture, clip_level, normalize_clip, ring_audio
from jarvis.core.matching import norm_phrase
from jarvis.core.routing import fast_end_phrases, grammar_phrases
from jarvis.core.state import ListenerState
from jarvis.core.wake import heard_after, phrase_finished, strip_wake, strip_wake_words

Config = dict[str, Any]
Word = dict[str, Any]
log = logging.getLogger("jarvis")



class VoskASR:
    """One Vosk model (``state.model``) for commands and free questions; recognizers are cheap to create."""

    def __init__(self, state: ListenerState) -> None:
        self.state = state
        self._fast: tuple[int, frozenset[str]] = (0, frozenset())
        self._names: tuple[int, NAMES.NameSet] = (0, NAMES.DEFAULT)
        self.missing_words: frozenset[str] = frozenset()   # grammar words the loaded model does not know

    def names(self, cfg: Config) -> NAMES.NameSet:
        """Enabled wake names of this configuration, without names the model cannot hear."""
        if self._names[0] != id(cfg): self._names = (id(cfg), NAMES.NameSet.from_cfg(cfg, self.missing_words))
        return self._names[1]

    def check_vocabulary(self, cfg: Config, phrases: Iterable[str] = ()) -> frozenset[str]:
        """Words of the name grammar and of ``phrases`` the loaded model lacks; each logged once as a WARNING.

        Vosk drops an unknown grammar word without an error, so a name or a protocol phrase with such a
        word would simply never be recognised."""
        model = self.state.model
        find = getattr(model, "vosk_model_find_word", None)
        if find is None: log.info("vocabulary check unavailable for this Vosk version"); return frozenset()
        words = NAMES.NameSet.from_cfg(cfg).vocabulary() | {w for p in phrases for w in norm_phrase(p)}
        missing = frozenset(w for w in sorted(words) if find(w) < 0)
        for w in sorted(missing - self.missing_words): log.warning("word %r is not in the Vosk model vocabulary; phrases with it are not recognised", w)
        self.missing_words = missing; self._names = (0, NAMES.DEFAULT)
        return missing

    def wake_hit(self, words: Sequence[Word], cfg: Config) -> tuple[list[Word], bool] | None:
        """Words of the first name the wake grammar heard and whether they are sure enough
        (``vosk_wake_min_conf``; names other than «Джарвис» also ``wake_alias_min_conf``); None without a name."""
        spans = self.names(cfg).spans([str(w.get("word", "")) for w in words])
        if not spans: return None
        a, b, name = spans[0]; ws = list(words[a:b])
        need = float(cfg["vosk_wake_min_conf"])
        if not name.primary: need = max(need, float(cfg.get("wake_alias_min_conf", NAMES.DEFAULTS["wake_alias_min_conf"])))
        return ws, min(float(w.get("conf", 0)) for w in ws) >= need

    def fast_phrases(self, cfg: Config) -> frozenset[str]:
        """routing.fast_end_phrases, rebuilt only when the configuration object changes (a reload)."""
        if self._fast[0] != id(cfg): self._fast = (id(cfg), fast_end_phrases(cfg))
        return self._fast[1]

    @staticmethod
    def load_model(path: str) -> Any:
        from vosk import Model
        return Model(path)

    @staticmethod
    def quiet() -> None:
        from vosk import SetLogLevel
        SetLogLevel(-1)

    def recognizer(self, grammar: Sequence[str] | None = None) -> Any:
        """A recognizer with word timings; restricted to ``grammar`` phrases when given."""
        from vosk import KaldiRecognizer
        r = (KaldiRecognizer(self.state.model, SR) if grammar is None
             else KaldiRecognizer(self.state.model, SR, json.dumps(list(grammar), ensure_ascii=False)))
        r.SetWords(True); return r

    def wake_recognizer(self, cfg: Config | None = None) -> Any:
        names = self.names(cfg) if cfg is not None else NAMES.DEFAULT
        return self.recognizer(names.grammar())

    def sleep_recognizer(self, cfg: Config | None = None) -> Any:
        names = self.names(cfg) if cfg is not None else NAMES.DEFAULT
        return self.recognizer(list(names.wake_phrases()) + list(names.hint_phrases()) + ["[unk]"])

    def stop_recognizer(self, cfg: Config) -> Any:
        ph = sorted(set(" ".join(norm_phrase(p)) for p in cfg.get("stop_phrases", [])) - {""})
        return self.recognizer(ph + ["[unk]"])

    def capture(self, cap: Capture, cfg: Config, nospeech_s: float, skip_s: float = 0.0, max_s: float | None = None,
                wake_pause_s: float | None = None) -> tuple[str, float, str]:
        """returns (text, avg_conf, grammar_text); wake_pause_s ends a bare «Джарвис» sooner."""
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(self.state.model, SR); rec.SetWords(True)
        try: rec.SetPartialWords(True)
        except Exception: pass
        grec: Any = None
        if cfg.get("grammar_hint", True):
            try: grec = KaldiRecognizer(self.state.model, SR, json.dumps(grammar_phrases(cfg), ensure_ascii=False)); grec.SetWords(True)
            except Exception as e: log.info("grammar recognizer failed: %s", e)
        agc = AGC(cfg)
        max_s = max_s or float(cfg["phrase_max_s"]); sil = float(cfg["phrase_silence_s"])
        fast_sil = min(sil, float(cfg.get("phrase_silence_fast_s", sil))); fast = self.fast_phrases(cfg) if fast_sil < sil else frozenset()
        fast_hit = False; names = self.names(cfg)
        words: list[Word] = []; gwords: list[Word] = []; t0 = time.time(); last_change: float | None = None; partial = ""; pwords: list[Word] | None = None; cut = True
        acoustic_last: float | None = None; noise_floor = 0.001; samples = 0; endpoint_lag = 0.0
        try:
            while time.time() - t0 < max_s:
                try: x = cap.q.get(timeout=0.15)
                except queue.Empty: x = None
                if x is not None:
                    samples += len(x)
                    rms = float(np.sqrt(np.mean(x * x)))
                    if rms > max(0.003, noise_floor * 3):
                        acoustic_last = cap.audio_start + samples / SR
                    else: noise_floor = 0.98 * noise_floor + 0.02 * min(rms, 0.004)
                    b = (agc(x) * 32767).astype(np.int16).tobytes()
                    if grec is not None and grec.AcceptWaveform(b): gwords += json.loads(grec.Result()).get("result", [])
                    if rec.AcceptWaveform(b):
                        ws = json.loads(rec.Result()).get("result", []); words += ws
                        if ws and not partial: last_change = time.time()
                        partial = ""
                    else:
                        pr = json.loads(rec.PartialResult()); p = pr.get("partial", "")
                        pwords = pr.get("partial_result") if "partial_result" in pr else (None if p else pwords)
                        if p != partial:
                            partial = p
                            if p: last_change = time.time()
                    if not cap.q.empty(): continue
                heard = heard_after(words, pwords if partial else [], partial, skip_s)
                # A phrase already heard whole as a safe command ends after the short silence.
                fast_hit = bool(fast) and " ".join(norm_phrase(strip_wake(heard, names))) in fast
                if phrase_finished(time.time(), t0, heard, last_change, acoustic_last, nospeech_s, fast_sil if fast_hit else sil,
                                   wake_pause_s, skip_s, names): cut = False; break
            words += json.loads(rec.FinalResult()).get("result", [])
            if grec is not None: gwords += json.loads(grec.FinalResult()).get("result", [])
        finally:
            if self.state.capture is cap: self.state.capture = None
        kept = [w for w in words if w.get("end", 99) > skip_s]
        kept = strip_wake_words(kept, self.names(cfg))
        text = " ".join(w["word"] for w in kept).strip()
        conf = sum(w.get("conf", 1) for w in kept) / len(kept) if kept else 0.0
        gk = [w for w in gwords if w.get("end", 99) > skip_s and w["word"] != "[unk]"]
        gtext = " ".join(w["word"] for w in gk); gconf = sum(w.get("conf", 1) for w in gk) / len(gk) if gk else 0.0
        gmin = min(agc.gains) if agc.gains else 1
        log.info("capture: raw=%r -> %r conf=%.2f | grammar=%r conf=%.2f | agc gain min=%.1f (%.1fs)",
                 " ".join(w["word"] for w in words), text, conf, gtext, gconf, gmin, time.time() - t0)
        if kept:
            endpoint_lag = max(0.0, time.time() - (cap.audio_start + kept[-1].get("end", 0)))
            log.info("capture endpoint lag_s=%.3f silence_s=%.2f%s (audio timestamp estimate)", endpoint_lag, fast_sil if fast_hit else sil,
                     " fast_end" if fast_hit else "")
        tr = self.state.trace
        if tr is not None and kept:
            tr.mark("speech_end", at=time.perf_counter() - endpoint_lag, estimated=True)
        self.state.last_input_conf = conf
        self.state.last_capture = {"words": kept, "hit_max": cut and bool(kept), "grammar_conf": round(gconf, 3) if gtext else 0.0}
        self.state.last_input_end = time.monotonic() - endpoint_lag if kept else None
        self.state.perf("recognized", confidence=round(conf,3))
        return text, conf, (gtext if gconf >= 0.75 else "")

    def free_words(self, audio: np.ndarray, cfg: Config, agc: bool = True) -> list[Word]:
        """Free-vocabulary transcript of a short clip (grammar recognizers force every sound into the wake word)."""
        r = self.recognizer(); gain = AGC(cfg) if agc else None
        for i in range(0, len(audio), CHUNK):
            part = audio[i:i + CHUNK]
            r.AcceptWaveform((np.clip(gain(part) if gain else part, -1, 1) * 32767).astype(np.int16).tobytes())
        result: list[Word] = json.loads(r.FinalResult()).get("result", [])
        return result

    def verify_wake(self, ring: Iterable[tuple[int, np.ndarray]], a: int, b: int, cfg: Config, need: Sequence[str] = (),
                    min_conf: float | None = None, owner: Callable[[], bool] | None = None) -> bool:
        """True when a free transcript of [a, b) contains the wake name (and every word in ``need``) confidently.

        The clip is read twice at most: lifted as a whole, then (if that fails) with the chunk AGC of live
        capture. A name heard only weakly still counts when ``owner`` confirms the owner's voice."""
        if not GATE.setting(cfg, "wake_verify_enabled"): return True
        t0 = time.monotonic(); raw = ring_audio(ring, a, b); peak, rms = clip_level(raw)
        mc = float(min_conf if min_conf is not None else GATE.setting(cfg, "wake_verify_min_conf"))

        def has_need(ws: list[Word], conf: float) -> bool:
            return all(any(w.get("word") == n and w.get("conf", 0) >= conf for w in ws) for n in need)

        names = self.names(cfg); alias_conf = float(cfg.get("wake_alias_min_conf", NAMES.DEFAULTS["wake_alias_min_conf"]))

        def confirmed(ws: list[Word], conf: float) -> bool:
            return bool(GATE.wake_word_confirmed(ws, conf, names, alias_conf)) and has_need(ws, conf)

        def owner_candidate(ws: list[Word], conf: float) -> bool:
            return (confirmed(ws, conf) or GATE.wake_soundalike_heard(ws, conf)) and has_need(ws, conf)

        clip, gain, agc = self.verify_clip(raw, cfg)
        passes = [self.free_words(clip, cfg, agc=agc)]
        ok = confirmed(passes[0], mc); how = "lifted" if not agc else "agc"
        if not ok and not agc:
            passes.append(self.free_words(raw, cfg)); ok = confirmed(passes[1], mc); how = "agc"
        owner_conf = float(GATE.setting(cfg, "wake_verify_owner_min_conf"))
        if not ok and owner is not None and any(owner_candidate(ws, owner_conf) for ws in passes):
            ok = owner(); how = "owner voice"
        log.info("wake verify %s (%s): free=%r level peak=%.3f rms=%.4f gain=%.1f (%.2fs)", "OK" if ok else "REJECTED", how,
                 " | ".join(" ".join("%s:%.2f" % (w.get("word"), w.get("conf", 0)) for w in ws) for ws in passes),
                 peak, rms, gain, time.monotonic() - t0)
        return ok

    @staticmethod
    def verify_clip(clip: np.ndarray, cfg: Config) -> tuple[np.ndarray, float, bool]:
        """(clip for the free pass, gain, whether chunk AGC still applies): quiet speech is lifted as a whole
        and framed by a little silence, so far-field «Джарвис» is not chopped by gain pumping."""
        if not GATE.setting(cfg, "wake_verify_normalize") or not len(clip): return clip, 1.0, True
        out, gain = normalize_clip(clip, float(GATE.setting(cfg, "wake_verify_target_peak")), float(GATE.setting(cfg, "wake_verify_max_gain")))
        pad = np.zeros(int(float(GATE.setting(cfg, "wake_verify_pad_s")) * SR), dtype=np.float32)
        return np.concatenate([pad, out, pad]), gain, False
