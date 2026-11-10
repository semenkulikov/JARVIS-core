from jarvis.core import wake as W


def test_wake_tail_is_not_speech():
    words = [{"word": "крыс", "start": 0.05, "end": 0.31, "conf": 1.0}]
    assert W.heard_after(words, None, "", W.VOSK_WAKE_SKIP_S) == []
    assert W.heard_after(words + [{"word": "брифинг", "end": 1.4}], None, "", W.VOSK_WAKE_SKIP_S) == ["брифинг"]
    assert W.heard_after([], [{"word": "есть", "end": 0.2}, {"word": "утренний", "end": 0.9}], "есть утренний", 0.4) == ["утренний"]
    assert W.heard_after([], None, "утренний", 0.4) == ["утренний"]


def test_tail_only_waits_for_the_command():
    # «Джарвис, … утренний брифинг»: the tail alone must not end the capture after 0.95 s of pause.
    f = lambda now, ac: W.phrase_finished(now, 0.0, [], 0.2, ac, 2.0, 0.95, None, 0.4)
    assert not f(1.5, 0.3)
    assert f(2.6, 0.3)


def test_bare_wake_on_vosk_path_answers_quickly():
    assert W.phrase_finished(1.2, 0.0, [], None, 0.3, 2.0, 0.95, 0.7, 0.4)
    assert not W.phrase_finished(1.2, 0.0, [], None, 0.9, 2.0, 0.95, 0.7, 0.4)  # still talking


def test_wake_only_then_short_pause():
    assert W.phrase_finished(2.0, 0.0, ["джарвис"], 1.2, 1.2, 2.0, 0.95, 0.7, 0.0)
    assert not W.phrase_finished(2.0, 0.0, ["утренний"], 1.2, 1.2, 2.0, 0.95, 0.7, 0.0)
    assert W.phrase_finished(2.3, 0.0, ["утренний"], 1.2, 1.2, 2.0, 0.95, 0.7, 0.0)


def test_strip_wake_words_drops_the_name_and_call_words():
    ws = [{"word": w} for w in ("хей", "джарвис", "ну", "который", "час")]
    assert [w["word"] for w in W.strip_wake_words(ws)] == ["который", "час"]
    assert W.strip_wake(["эй", "джарвис", "стоп"]) == "стоп"


def test_a_project_named_after_the_assistant_keeps_its_name():
    ws = [{"word": w} for w in ("джарвис", "открой", "проект", "джарвис")]
    assert [w["word"] for w in W.strip_wake_words(ws)] == ["открой", "проект", "джарвис"]
    ws = [{"word": w} for w in ("открой", "проект", "джарвис")]
    assert [w["word"] for w in W.strip_wake_words(ws)] == ["открой", "проект", "джарвис"]
    ws = [{"word": w} for w in ("шум", "какой", "джарвис")]  # pre-buffer noise before a bare call
    assert W.strip_wake_words(ws) == []
