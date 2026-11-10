import json
import sys
import types

import numpy as np

from jarvis.adapters.asr_vosk import VoskASR
from jarvis.adapters.audio import CHUNK, Capture
from jarvis.core.state import ListenerState


class FakeRecognizer:
    """Hears «джарвис который час» on the second frame of the free recognizer."""

    def __init__(self, model, sr, grammar=None):
        self.grammar = json.loads(grammar) if grammar else None; self.n = 0
    def SetWords(self, on): pass
    def SetPartialWords(self, on): pass
    def AcceptWaveform(self, b):
        self.n += 1
        return self.grammar is None and self.n == 2
    def Result(self):
        return json.dumps({"result": [{"word": "джарвис", "conf": 1.0, "end": 0.5}, {"word": "который", "conf": 0.9, "end": 0.9},
                                      {"word": "час", "conf": 0.8, "end": 1.1}]})
    def PartialResult(self): return json.dumps({"partial": ""})
    def FinalResult(self): return json.dumps({"result": []})


def test_capture_strips_the_name_and_records_the_turn(monkeypatch, cfg):
    monkeypatch.setitem(sys.modules, "vosk", types.SimpleNamespace(KaldiRecognizer=FakeRecognizer))
    st = ListenerState(model=object())
    cap = Capture([np.full(CHUNK, 0.1, np.float32), np.full(CHUNK, 0.1, np.float32)])
    st.capture = cap
    text, conf, gtext = VoskASR(st).capture(cap, dict(cfg, phrase_silence_s=0.05, phrase_max_s=2.0), 0.3)
    assert (text, round(conf, 2), gtext) == ("который час", 0.85, "")
    assert st.capture is None and st.last_input_conf == conf and [w["word"] for w in st.last_capture["words"]] == ["который", "час"]


def test_stop_grammar_uses_normalised_phrases(monkeypatch, cfg):
    monkeypatch.setitem(sys.modules, "vosk", types.SimpleNamespace(KaldiRecognizer=FakeRecognizer))
    rec = VoskASR(ListenerState()).stop_recognizer(dict(cfg, stop_phrases=["Стоп!", "хватит", ""]))
    assert rec.grammar == ["стоп", "хватит", "[unk]"]
