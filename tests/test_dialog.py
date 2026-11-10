import threading

import pytest

import jarvis_commands as Q
import jarvis_dialog as D
from test_commands import FakeBackend


@pytest.mark.parametrize("alias,key", [
    ({"action": "quick2", "cmd": "timer"}, "ack_action"),
    ({"action": "quick2", "cmd": "reminder"}, "ack_action"),
    ({"action": "quick2", "cmd": "mode", "mode": "focus"}, "ack_action"),
    ({"action": "quick2", "cmd": "mode", "mode": "sleep"}, None),
    ({"action": "quick2", "cmd": "server_health"}, "ack_lookup"),
    ({"action": "quick2", "cmd": "nutrition_left"}, "ack_lookup"),
    ({"action": "quick2", "cmd": "food_log"}, "ack_food"),
    ({"action": "quick2", "cmd": "repeat"}, None),
    ({"action": "quick2", "cmd": "volume"}, None),
    ({"action": "quick2", "cmd": "clipboard_read"}, None),
    ({"action": "quick2", "cmd": "todoist_add"}, None),
    ({"action": "quick2", "cmd": "shutdown_prepare"}, None),
    ({"action": "time"}, None),
    ({"action": "jarvis_sleep"}, None),
    (None, None),
])
def test_ack_key_policy(alias, key):
    assert D.ack_key(alias) == key


def test_ack_plays_first_while_work_runs_in_parallel():
    events = []
    started = threading.Event()

    def say(text, cfg, **kw):
        if kw.get("role") == "ack":
            assert started.wait(1), "work must start before the ack finishes"
        events.append(text)
        return True

    def work(speak):
        started.set()
        events.append("work")
        speak("Готово, сэр.")
        return 42

    assert D.ack_then(say, {}, "Есть, сэр.", work) == 42
    assert events == ["work", "Есть, сэр.", "Готово, сэр."]


def test_ack_then_reraises_and_skips_empty_ack():
    said = []
    with pytest.raises(ValueError):
        D.ack_then(lambda t, c, **k: said.append(t), {}, "Есть, сэр.", lambda s: (_ for _ in ()).throw(ValueError()))
    assert said == ["Есть, сэр."]
    assert D.ack_then(lambda t, c, **k: said.append(t), {}, "", lambda s: s("ok", {}) or 1) == 1


def test_phrase_lists_cover_every_ack():
    phrases = D.phrase_lists({})
    for key in ("ack_wake",) + D.ACK_KEYS:
        assert set(D.DEFAULTS[key]) <= set(phrases)


def test_quick_timer_gets_ack_then_result(listener, cfg, monkeypatch, tmp_path):
    out = []
    monkeypatch.setattr(listener, "say", lambda t, c, **k: out.append(t) or True)
    ctl = Q.Controller(tmp_path, FakeBackend())
    monkeypatch.setattr(listener, "command_controller", lambda: ctl)
    al = listener.match_alias("поставь таймер на пять минут", cfg)
    listener.run_alias(al, "поставь таймер на пять минут", cfg, "wake_word", False)
    assert out[0] in D.DEFAULTS["ack_action"] and out[1] == "Таймер сохранён на пять минут, сэр."


def test_instant_answer_has_no_ack(listener, cfg, monkeypatch, tmp_path):
    out = []
    monkeypatch.setattr(listener, "say", lambda t, c, **k: out.append(t) or True)
    monkeypatch.setattr(listener, "command_controller", lambda: Q.Controller(tmp_path, FakeBackend()))
    listener.run_alias({"name": "q", "action": "quick2", "cmd": "volume", "value": 40}, "громкость сорок", cfg, "wake_word", False)
    assert out == ["Громкость 40 процентов, сэр."]


def test_server_ack_varies_and_never_repeats(listener, cfg):
    picks = [listener.pick(cfg, "ack_server") for _ in range(20)]
    assert all(a != b for a, b in zip(picks, picks[1:], strict=False))


def test_only_wake_heard(listener):
    assert listener.only_wake_heard([{"word": "джарвис"}], "")
    assert listener.only_wake_heard([], "хей джарвис")
    assert not listener.only_wake_heard([{"word": "джарвис"}], "поставь")
    assert not listener.only_wake_heard([], "")


def test_wake_ack_phrases_precached(listener, cfg):
    assert "Я здесь, сэр." in listener.all_phrases(cfg)


def test_ack_and_sleep_words_are_stressed(cfg):
    import jarvis_text as JT
    out = JT.apply_dict("Выполняю, сэр. Я в спящем режиме. Разбудить: Джарвис, проснись.", cfg)
    assert "Выполн+яю" in out and "сп+ящем реж+име" in out and "просн+ись" in out
