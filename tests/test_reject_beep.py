"""A dropped phrase after the name: a short low tone instead of silence, rate-limited and never on follow-ups."""
import logging

import numpy as np
import pytest

from jarvis.adapters import tts as TTS
from jarvis.core import dialog as DIALOG


@pytest.mark.parametrize("trig,enabled,last,now,due", [
    ("wake_word", True, 0.0, 10.0, True),
    ("clap", True, 0.0, 10.0, True),
    ("followup", True, 0.0, 10.0, False),     # background speech in the follow-up window: silent
    ("wake_word", False, 0.0, 10.0, False),   # switched off
    ("wake_word", True, 9.0, 10.0, False),    # within the minimum interval
    ("wake_word", True, 7.0, 10.0, True),     # exactly the interval later
])
def test_reject_beep_flag_trigger_and_interval(trig, enabled, last, now, due):
    cfg = {"reject_beep_enabled": enabled, "reject_beep_min_interval_s": 3}
    assert DIALOG.reject_beep_due(cfg, trig, last, now) is due


def test_reject_tone_is_low_short_and_click_free():
    tone = TTS.reject_tone()
    assert 0.15 < len(tone) / TTS.SR < 0.3 and abs(tone[0]) < 1e-3 and abs(tone[-1]) < 0.02 and np.abs(tone).max() <= 0.31
    spectrum = np.abs(np.fft.rfft(tone)); peak_hz = np.argmax(spectrum) * TTS.SR / len(tone)
    assert 200 < peak_hz < 350  # far below the 880 Hz timer beep


@pytest.fixture
def beeps(app, cfg, monkeypatch):
    out = []
    monkeypatch.setattr(app.c.voice, "beep_reject", lambda: out.append(1))
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: True)
    return out


def captured(app, monkeypatch, text, conf, words_conf):
    def capture(cap, cfg, *a, **k):
        app.c.state.last_capture = {"words": [{"word": w, "conf": words_conf} for w in text.split()], "hit_max": False, "grammar_conf": 0.0}
        return text, conf, ""
    monkeypatch.setattr(app.conversation, "capture", capture)


def test_name_then_unclear_phrase_beeps_and_logs_the_reason(app, cfg, beeps, monkeypatch, caplog):
    captured(app, monkeypatch, "шатра стяжка муфта", 0.4, 0.4)
    with caplog.at_level(logging.INFO, logger="jarvis"):
        app.conversation.handle_turn("wake_word", object(), None, False, 0.0)
    assert beeps == [1] and "not understood -> beep (low_confidence)" in caplog.text


def test_second_drop_within_the_interval_is_silent(app, cfg, beeps, monkeypatch, caplog):
    captured(app, monkeypatch, "шатра стяжка муфта", 0.4, 0.4)
    with caplog.at_level(logging.INFO, logger="jarvis"):
        app.conversation.handle_turn("wake_word", object(), None, False, 0.0)
        app.conversation.handle_turn("clap", object(), None, False, 0.0)
    assert beeps == [1] and "not understood -> silent (low_confidence)" in caplog.text


def test_followup_drop_stays_silent(app, cfg, beeps, monkeypatch):
    app.conversation.not_understood("followup", cfg, "low_confidence", "что-то")
    assert beeps == []


def test_disabled_flag_keeps_silence(app, cfg, beeps, monkeypatch):
    cfg["reject_beep_enabled"] = False
    captured(app, monkeypatch, "шатра стяжка муфта", 0.4, 0.4)
    app.conversation.handle_turn("wake_word", object(), None, False, 0.0)
    assert beeps == []
