import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import enroll_speaker as E  # noqa: E402
import jarvis_commands as Q  # noqa: E402
import jarvis_sleep as SLEEP  # noqa: E402
from jarvis.core import routing as ROUTING


def _bare(phrase):
    t = phrase.lower().replace("ё", "е")
    for ch in ",.?!—":
        t = t.replace(ch, " ")
    words = t.split()
    while words and words[0] in ("хей", "джарвис"):
        words.pop(0)
    return " ".join(words)


@pytest.mark.parametrize("phrase", E.PHRASES)
def test_enrollment_phrases_are_not_commands(phrase):
    text = _bare(phrase)
    assert Q.match(text) is None and SLEEP.parse(text) is None


def test_listener_paused_stops_and_restarts(tmp_path, monkeypatch):
    state = {"on": True, "calls": []}
    monkeypatch.setattr(E.D, "wait_for", lambda pred, timeout, step=0.5: pred())
    stop = lambda: (state["calls"].append("stop"), state.update(on=False))
    start = lambda: state["calls"].append("start")
    with E.listener_paused(tmp_path, stop=stop, start=start, running=lambda: state["on"]) as was:
        assert was and state["calls"] == ["stop"]
    assert state["calls"] == ["stop", "start"]


def test_listener_paused_noop_when_not_running(tmp_path):
    calls = []
    with E.listener_paused(tmp_path, stop=lambda: calls.append("stop"), start=lambda: calls.append("start"), running=lambda: False) as was:
        assert not was
    assert calls == []


@pytest.mark.parametrize("phrase", E.PHRASES)
def test_enrollment_phrases_match_no_alias(app, cfg, phrase):
    assert ROUTING.match_alias(_bare(phrase), cfg) is None
