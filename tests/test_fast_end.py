"""Two silence thresholds: a phrase already heard whole as a safe command ends after the short one."""
import time

import pytest

from jarvis.core import routing as ROUTING
from jarvis.core.wake import phrase_finished


@pytest.mark.parametrize("text,fast", [
    ("громче", True), ("тише", True), ("пауза", True), ("дальше", True), ("который час", True), ("стоп", True),
    ("Который час", True), ("сводка", True),
    ("таймер на пять минут", False), ("поставь таймер", False), ("открой проект джарвис", False),
    ("выключи компьютер", False), ("заблокируй экран", False), ("какая погода завтра", False),
    ("статус", False),   # «статус по задачам» starts with it: wait for the rest
    ("повтори", False),  # «повтори помедленнее»
])
def test_fast_end_table(cfg, text, fast):
    assert ROUTING.fast_end_eligible(text, cfg) is fast


def test_alias_flag_overrides_the_rule(cfg):
    cfg["aliases"] = cfg["aliases"] + [{"name": "lamp", "phrases": ["включи лампу"], "action": "shell", "fast_end": True}]
    for al in cfg["aliases"]:
        if al["name"] == "vol_up": al["fast_end"] = False
    assert ROUTING.fast_end_eligible("включи лампу", cfg) and not ROUTING.fast_end_eligible("громче", cfg)


def test_a_longer_phrase_with_the_same_start_blocks_it(cfg):
    cfg["aliases"] = cfg["aliases"] + [{"name": "vol5", "phrases": ["громче на пять"], "action": "key", "key": "vol_up"}]
    assert not ROUTING.fast_end_eligible("громче", cfg) and ROUTING.fast_end_eligible("громче на пять", cfg)


def test_short_threshold_ends_sooner():
    now = time.time()
    heard = ["громче"]
    assert phrase_finished(now, now - 2, heard, now - 0.5, now - 0.5, 1.5, 0.45)
    assert not phrase_finished(now, now - 2, heard, now - 0.5, now - 0.5, 1.5, 0.95)


class FakeRec:
    """Vosk stand-in: says «громче» at once and then hears silence."""
    def __init__(self, *a): pass
    def SetWords(self, v): pass
    def SetPartialWords(self, v): pass
    def AcceptWaveform(self, b): return False
    def PartialResult(self): return '{"partial": "громче", "partial_result": [{"word": "громче", "conf": 1, "start": 0.1, "end": 0.4}]}'
    def FinalResult(self): return '{"result": [{"word": "громче", "conf": 1.0, "start": 0.1, "end": 0.4}]}'
    def Result(self): return '{"result": []}'


@pytest.mark.parametrize("fast_s,low,high", [(0.45, 0.4, 0.8), (0.95, 0.9, 1.4)])
def test_capture_uses_the_fast_threshold_for_a_safe_phrase(app, cfg, monkeypatch, fast_s, low, high):
    import sys
    import types

    import numpy as np

    from jarvis.adapters.audio import CHUNK, Capture
    vosk = types.ModuleType("vosk"); vosk.KaldiRecognizer = FakeRec
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    cfg.update(grammar_hint=False, phrase_silence_fast_s=fast_s, phrase_silence_s=0.95)
    cap = Capture(); loud = np.full(CHUNK, 0.2, np.float32)
    cap.q.put(loud)
    t = time.time()
    text, _, _ = app.c.asr.capture(cap, cfg, nospeech_s=3.0)
    assert text == "громче" and low <= time.time() - t < high
