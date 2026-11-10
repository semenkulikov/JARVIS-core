

def test_wake_tail_is_not_speech(listener):
    words = [{"word": "крыс", "start": 0.05, "end": 0.31, "conf": 1.0}]
    assert listener.heard_after(words, None, "", listener.VOSK_WAKE_SKIP_S) == []
    assert listener.heard_after(words + [{"word": "брифинг", "end": 1.4}], None, "", listener.VOSK_WAKE_SKIP_S) == ["брифинг"]
    assert listener.heard_after([], [{"word": "есть", "end": 0.2}, {"word": "утренний", "end": 0.9}], "есть утренний", 0.4) == ["утренний"]
    assert listener.heard_after([], None, "утренний", 0.4) == ["утренний"]


def test_tail_only_waits_for_the_command(listener):
    # «Джарвис, … утренний брифинг»: the tail alone must not end the capture after 0.95 s of pause.
    f = lambda now, ac: listener.phrase_finished(now, 0.0, [], 0.2, ac, 2.0, 0.95, None, 0.4)
    assert not f(1.5, 0.3)
    assert f(2.6, 0.3)


def test_bare_wake_on_vosk_path_answers_quickly(listener):
    assert listener.phrase_finished(1.2, 0.0, [], None, 0.3, 2.0, 0.95, 0.7, 0.4)
    assert not listener.phrase_finished(1.2, 0.0, [], None, 0.9, 2.0, 0.95, 0.7, 0.4)  # still talking


def test_wake_only_then_short_pause(listener):
    assert listener.phrase_finished(2.0, 0.0, ["джарвис"], 1.2, 1.2, 2.0, 0.95, 0.7, 0.0)
    assert not listener.phrase_finished(2.0, 0.0, ["утренний"], 1.2, 1.2, 2.0, 0.95, 0.7, 0.0)
    assert listener.phrase_finished(2.3, 0.0, ["утренний"], 1.2, 1.2, 2.0, 0.95, 0.7, 0.0)
