import datetime
import threading

import pytest

import jarvis_commands as Q
from jarvis.core import dialog as D
from jarvis.core import phrases as P
from jarvis.core import wake as W
from test_commands import FakeBackend
from jarvis.core import routing as ROUTING


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


def test_quick_timer_gets_ack_then_result(app, cfg, monkeypatch, tmp_path):
    out = []
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: out.append(t) or True)
    ctl = Q.Controller(tmp_path, FakeBackend())
    monkeypatch.setattr(app.conversation, "controller", lambda: ctl)
    al = ROUTING.match_alias("поставь таймер на пять минут", cfg)
    app.conversation.run_alias(al, "поставь таймер на пять минут", cfg, "wake_word", False)
    assert out[0] in D.DEFAULTS["ack_action"] and out[1] == "Таймер сохранён на пять минут, сэр."


def test_instant_answer_has_no_ack(app, cfg, monkeypatch, tmp_path):
    out = []
    monkeypatch.setattr(app.conversation, "say", lambda t, c, **k: out.append(t) or True)
    monkeypatch.setattr(app.conversation, "controller", lambda: Q.Controller(tmp_path, FakeBackend()))
    app.conversation.run_alias({"name": "q", "action": "quick2", "cmd": "volume", "value": 40}, "громкость сорок", cfg, "wake_word", False)
    assert out == ["Громкость 40 процентов, сэр."]


def test_server_ack_varies_and_never_repeats(app, cfg):
    picks = [app.conversation.pick(cfg, "ack_server") for _ in range(20)]
    assert all(a != b for a, b in zip(picks, picks[1:], strict=False))


def test_only_wake_heard():
    assert W.only_wake_heard([{"word": "джарвис"}], "")
    assert W.only_wake_heard([], "хей джарвис")
    assert not W.only_wake_heard([{"word": "джарвис"}], "поставь")
    assert not W.only_wake_heard([], "")


def test_wake_ack_phrases_precached(cfg):
    assert "Я здесь, сэр." in P.all_phrases(cfg)


def test_picker_never_repeats_and_falls_back_to_defaults():
    picker = P.Picker({"ack": ["а", "б"]})
    picks = [picker.pick({}, "ack") for _ in range(10)]
    assert all(a != b for a, b in zip(picks, picks[1:], strict=False)) and set(picks) == {"а", "б"}
    assert picker.pick({"ack": "один"}, "ack") == "один"


def test_smalltalk_reply_fills_the_daypart():
    al = {"name": "chat_bye", "replies": ["До свидания, сэр. Хорошего {daypart}."]}
    assert P.smalltalk_reply(al, P.Picker({}), datetime.datetime(2026, 1, 1, 20)) == "До свидания, сэр. Хорошего вечера."


def test_ack_and_sleep_words_are_stressed(cfg):
    from jarvis.core import text as JT
    out = JT.apply_dict("Выполняю, сэр. Я в спящем режиме. Разбудить: Джарвис, проснись.", cfg)
    assert "Выполн+яю" in out and "сп+ящем реж+име" in out and "просн+ись" in out
