"""v3.14: strict wake, silent drops, <silent> replies and Jarvis sleep mode (model-free)."""
import time

import numpy as np
import pytest

import jarvis_gate as GATE
import jarvis_sleep as SLEEP
from jarvis.core.followup import FollowupSettings, followup_seconds
from jarvis.core import routing as ROUTING


def words(text, conf):
    return [{"word": w, "conf": conf} for w in text.split()]


# Real false triggers from the 10.11 log (English lesson in the background).
GARBAGE = [
    ("то есть", 0.65, False, False),
    ("знать", 0.48, False, False),
    ("захочешь память а способ локтях мого они приехали а не бегая вей мужа", 0.65, True, True),
    ("тошнота стой муфта и вы симонова", 0.74, True, True),
    ("джордж", 0.67, True, False),
    ("очень туалете окей тогда масса семьдесят шесть ноль они мне казалось что я поблажек", 0.75, False, True),
    ("гаррис шатра и твоим аш вас дозу стяжка старик", 0.71, False, True),
]


@pytest.mark.parametrize("text,conf,followup,hit_max", GARBAGE)
def test_logged_garbage_is_rejected(text, conf, followup, hit_max):
    assert GATE.reject_reason(words(text, conf), GATE.DEFAULTS, followup=followup, hit_max=hit_max)


@pytest.mark.parametrize("text,conf,followup", [
    ("сэр статус", 1.0, False),
    ("доброе утро", 1.0, False),
    ("какая погода завтра в париже", 0.9, False),
    ("а что по питанию", 0.92, True),
])
def test_clear_commands_pass(text, conf, followup):
    assert GATE.reject_reason(words(text, conf), GATE.DEFAULTS, followup=followup, hit_max=False) is None


def test_mostly_unsure_words_rejected():
    ws = words("открой мне окно", 0.99) + words("шатра стяжка", 0.55)
    assert GATE.reject_reason(ws, GATE.DEFAULTS, followup=False, hit_max=False) == "unsure_words"


@pytest.mark.parametrize("ws,ok", [
    ([{"word": "джарвис", "conf": 0.93}], True),
    ([{"word": "хей", "conf": 1}, {"word": "джарвиса", "conf": 0.85}], True),
    ([{"word": "джарвис", "conf": 0.55}], False),
    ([{"word": "то", "conf": 1}, {"word": "есть", "conf": 1}], False),
    ([{"word": "гаррис", "conf": 0.99}], False),
    ([], False),
])
def test_wake_word_confirmed(ws, ok):
    assert GATE.wake_word_confirmed(ws, 0.8) is ok


@pytest.mark.parametrize("text", ["", "<silent>", " <SILENT>\n", "[silent]"])
def test_silent_marker(text):
    assert GATE.is_silent_reply(text)


def test_silent_marker_not_text():
    assert not GATE.is_silent_reply("Готово, сэр.")


@pytest.mark.parametrize("text,secs", [
    ("спящий режим на тридцать минут", 1800),
    ("засни на час", 3600),
    ("режим сна на час", 3600),
    ("спящий режим", 3600),
    ("Джарвис, спящий режим на два часа", 7200),
    ("усни на полчаса", 1800),
    ("перейди в спящий режим на сорок пять минут", 2700),
    ("засни на 20 минут", 1200),
    ("спи на пять минут", 300),
    ("включи спящий режим на сутки", 3600),
])
def test_sleep_phrases(text, secs):
    assert SLEEP.parse(text) == secs


@pytest.mark.parametrize("text", ["режим сна", "включи режим сна", "что такое спящий режим", "сон", "статус"])
def test_not_sleep_phrases(text):
    assert SLEEP.parse(text) is None


def test_sleep_clamped():
    assert SLEEP.parse("засни на тридцать секунд") == SLEEP.MIN_S
    assert SLEEP.parse("засни на двадцать часов") == SLEEP.MAX_S


def test_sleep_state_persists_and_expires(tmp_path):
    now = [1000.0]
    st = SLEEP.SleepState(tmp_path / "sleep.json", clock=lambda: now[0])
    st.start(600)
    again = SLEEP.SleepState(tmp_path / "sleep.json", clock=lambda: now[0])
    assert again.active() and again.remaining() == 600
    now[0] += 599
    assert again.poll() is None
    now[0] += 2
    assert again.poll() == "timeout" and not again.active() and again.poll() is None
    assert not SLEEP.SleepState(tmp_path / "sleep.json", clock=lambda: now[0]).active()


def test_wake_file_ends_sleep(tmp_path):
    st = SLEEP.SleepState(tmp_path / "sleep.json")
    st.start(3600)
    wake = tmp_path / "wake_up"
    wake.write_text("")
    assert st.poll(wake) == "wake_file" and not wake.exists() and not st.active()


def test_corrupt_state_means_awake(tmp_path):
    (tmp_path / "sleep.json").write_text("{oops", encoding="utf-8")
    assert not SLEEP.SleepState(tmp_path / "sleep.json").active()


@pytest.mark.parametrize("text", ["джарвис проснись", "Проснись Джарвис"])
def test_wake_phrases(text):
    assert SLEEP.is_wake_phrase(text)


@pytest.mark.parametrize("text", ["проснись", "джарвис", "джарвис проснулся"])
def test_not_wake_phrases(text):
    assert not SLEEP.is_wake_phrase(text)


# ---------------------------------------------------------------- listener integration
@pytest.fixture
def said(listener, monkeypatch):
    out = []
    monkeypatch.setattr(listener, "say", lambda t, c, **k: out.append(t))
    monkeypatch.setattr(listener, "say_reply", lambda t, c, **k: out.append(t))
    return out


def test_sleep_command_is_local(listener, cfg):
    al = ROUTING.match_alias("засни на час", cfg)
    assert al["action"] == "jarvis_sleep" and al["seconds"] == 3600


def test_legacy_sleep_mode_unchanged(listener, cfg):
    al = ROUTING.match_alias("режим сна", cfg)
    assert al["action"] == "quick2" and al["mode"] == "sleep"


def test_run_sleep_alias_starts_sleep(listener, cfg, said, monkeypatch, tmp_path):
    st = SLEEP.SleepState(tmp_path / "sleep.json")
    monkeypatch.setattr(listener, "SLEEP_STATE", st)
    al = ROUTING.match_alias("спящий режим на тридцать минут", cfg)
    listener.run_alias(al, "спящий режим на тридцать минут", cfg, "wake_word", False)
    assert st.active() and 1790 < st.remaining() <= 1800
    assert said and "спящий режим" in said[0] and listener.STATE.followup_eligible is False


def test_run_sleep_alias_test_mode_no_state(listener, cfg, said, monkeypatch, tmp_path):
    st = SLEEP.SleepState(tmp_path / "sleep.json")
    monkeypatch.setattr(listener, "SLEEP_STATE", st)
    listener.run_alias({"name": "jarvis_sleep", "action": "jarvis_sleep", "seconds": 60}, "засни", cfg, "wake_word", True)
    assert not st.active()


def test_low_conf_sleep_rejected(listener, cfg):
    listener.STATE.last_capture = None
    assert listener.choose("засни на час", 0.4, "", cfg) == ("засни на час", False)


@pytest.mark.parametrize("text,conf,followup,hit_max", GARBAGE)
def test_choose_drops_garbage_silently(listener, cfg, text, conf, followup, hit_max):
    listener.STATE.last_capture = {"words": words(text, conf), "hit_max": hit_max}
    assert listener.choose(text, conf, "", cfg, followup=followup) == ("", False)
    assert listener.STATE.dropped is True


def test_choose_continuous_speech_dropped(listener, cfg):
    listener.STATE.last_capture = {"words": words("какая погода завтра", 0.95), "hit_max": True}
    assert listener.choose("какая погода завтра", 0.95, "", cfg) == ("", False)


def test_choose_clear_free_phrase_passes(listener, cfg):
    listener.STATE.last_capture = {"words": words("какая погода завтра", 0.95), "hit_max": False}
    assert listener.choose("какая погода завтра", 0.95, "", cfg) == ("какая погода завтра", True)


def test_followup_ignores_grammar_guess(listener, cfg):
    listener.STATE.last_capture = {"words": words("в вашем", 0.85), "hit_max": False}
    assert listener.choose("в вашем", 0.85, "статус по задачам", cfg, followup=True)[1] is False


def test_garbled_wake_turn_says_nothing(listener, cfg, said, monkeypatch):
    def fake_capture(cap, c, nospeech, skip_s=0.0, max_s=None):
        listener.STATE.last_capture = {"words": words("то есть", 0.65), "hit_max": False}
        return "то есть", 0.65, ""
    monkeypatch.setattr(listener, "capture_phrase", fake_capture)
    monkeypatch.setattr(listener, "free_phrase", lambda *a, **k: pytest.fail("garbage must not reach the server"))
    listener._handle_turn("wake_word", listener.Capture(), None, False, 0.0)
    assert said == []


def test_not_understood_phrase_never_spoken(listener, cfg, said, monkeypatch):
    seq = iter([("", 0.0, ""), ("знать", 0.48, "")])
    def fake_capture(cap, c, nospeech, skip_s=0.0, max_s=None):
        t, cf, g = next(seq)
        listener.STATE.last_capture = {"words": words(t, cf) if t else [], "hit_max": False}
        return t, cf, g
    monkeypatch.setattr(listener, "capture_phrase", fake_capture)
    listener._handle_turn("wake_word", listener.Capture(), None, False, 0.0)
    assert not any("расслышал" in s or "разобрал" in s for s in said)


def test_followup_window_capped(cfg):
    cfg.update(followup_window_s=7.0, followup_question_window_s=10.0)
    assert followup_seconds(cfg, "Что прикажете?") == 6.0
    assert followup_seconds(cfg, "Готово.") == 6.0


def test_followup_settings_clamp_and_question_window(cfg):
    cfg.update(followup_window_s=3.0, followup_question_window_s=5.0, followup_echo_guard_s=9, followup_max_turns=-2)
    fs = FollowupSettings.from_cfg(cfg)
    assert (fs.window_for("Да?"), fs.window_for("Да."), fs.echo_guard_s, fs.max_turns) == (5.0, 3.0, 2.0, 0)


class _Sig:
    def clear(self): pass
    def wait(self, cfg): time.sleep(0.01)


@pytest.fixture
def outbox(listener, cfg, said, monkeypatch, tmp_path):
    monkeypatch.setattr(listener, "OUTBOX", str(tmp_path))
    monkeypatch.setattr(listener, "DONE", str(tmp_path))
    monkeypatch.setattr(listener, "OUTBOX_SIGNAL", _Sig())
    listener.interrupt.clear(); listener.LEDGER.down_since = None
    cfg.update(reply_timeout_s=3.0, server_notice_s=5.0, server_down_wait_s=5.0)
    return tmp_path


@pytest.mark.parametrize("body", ["<silent>", ""])
def test_silent_final_speaks_nothing(listener, cfg, said, outbox, body):
    (outbox / "s1.txt").write_text(body, encoding="utf-8")
    t = time.time()
    assert listener.wait_replies("s1", cfg, listener_ack="Сейчас, сэр.") is True
    assert said == [] and time.time() - t < 2.5


def test_silent_after_parts_keeps_parts(listener, cfg, said, outbox):
    (outbox / "s2.1.txt").write_text("Первая часть.", encoding="utf-8")
    (outbox / "s2.txt").write_text("<silent>", encoding="utf-8")
    assert listener.wait_replies("s2", cfg) is True and said == ["Первая часть."]



def test_ring_audio(listener):
    ring = [(0, np.arange(10, dtype=np.float32)), (10, np.arange(10, 20, dtype=np.float32))]
    assert listener.ring_audio(ring, 5, 15).tolist() == list(range(5, 15))
    assert listener.ring_audio(ring, 30, 40).size == 0


@pytest.mark.parametrize("free,need,ok", [
    ([{"word": "джарвис", "conf": 0.95}], (), True),
    ([{"word": "то", "conf": 1.0}, {"word": "есть", "conf": 1.0}], (), False),
    ([{"word": "джарвис", "conf": 0.95}], ("проснись",), False),
    ([{"word": "джарвис", "conf": 0.95}, {"word": "проснись", "conf": 0.9}], ("проснись",), True),
])
def test_verify_wake(listener, cfg, monkeypatch, free, need, ok):
    cfg["wake_verify_min_conf"] = 0.8
    monkeypatch.setattr(listener, "free_words", lambda model, audio, c: free)
    assert listener.verify_wake(None, [], 0, 10, cfg, need=need) is ok


def test_verify_wake_disabled(listener, cfg, monkeypatch):
    cfg["wake_verify_enabled"] = False
    monkeypatch.setattr(listener, "free_words", lambda *a: pytest.fail("must not decode"))
    assert listener.verify_wake(None, [], 0, 10, cfg) is True


def test_sleep_wake_needs_higher_conf(listener, cfg, monkeypatch):
    monkeypatch.setattr(listener, "free_words", lambda *a: [{"word": "джарвис", "conf": 0.75}, {"word": "проснись", "conf": 0.99}])
    assert listener.verify_wake(None, [], 0, 10, cfg) is True
    assert listener.verify_wake(None, [], 0, 10, cfg, need=("проснись",), min_conf=0.85) is False


def test_grammar_settles_garbled_safe_command(listener, cfg):
    assert listener.choose("что пить проекта пример", 0.9, "что в гите проекта пример", cfg) == ("что в гите проекта пример", True)


@pytest.mark.parametrize("text,gtext", [("почему небо голубое", "помедленнее"),
                                        ("добав двести грамм торга", "добавь двести грамм творога")])
def test_grammar_never_forces_free_questions_or_writes(listener, cfg, text, gtext):
    assert listener.choose(text, 0.9, gtext, cfg)[0] != gtext


def test_grammar_rescue_not_in_followup_or_when_disabled(listener, cfg):
    assert listener.choose("что пить проекта пример", 0.9, "что в гите проекта пример", cfg, followup=True)[0] != "что в гите проекта пример"
    cfg["grammar_command_rescue"] = False
    assert listener.choose("что пить проекта пример", 0.9, "что в гите проекта пример", cfg)[0] != "что в гите проекта пример"


def test_enter_phrase_has_duration_words_and_wake_hint():
    assert SLEEP.enter_phrase(7200) == "Ухожу в спящий режим на два часа, сэр. Разбудить: Джарвис, проснись."
    assert "на час," in SLEEP.enter_phrase(3600) and "на сорок пять минут," in SLEEP.enter_phrase(2700)


def test_hint_phrase_rounds_remaining_minutes():
    assert SLEEP.hint_phrase(1795).startswith("Я в спящем режиме ещё полчаса, сэр.")
    assert "ещё минуту" in SLEEP.hint_phrase(5)


def test_sleep_alias_announces_how_to_wake(listener, cfg, said, monkeypatch, tmp_path):
    monkeypatch.setattr(listener, "SLEEP_STATE", SLEEP.SleepState(tmp_path / "sleep.json"))
    listener.run_alias({"name": "jarvis_sleep", "action": "jarvis_sleep", "seconds": 3600}, "засни", cfg, "wake_word", True)
    assert said == ["Ухожу в спящий режим на час, сэр. Разбудить: Джарвис, проснись."]


def test_sleep_hint_rate_limited(listener, cfg, monkeypatch):
    listener.STATE.sleep_hint_at = 0
    assert listener.sleep_hint_due(cfg)
    listener.STATE.sleep_hint_at = listener.time.time()
    assert not listener.sleep_hint_due(cfg)
    assert not listener.sleep_hint_due(dict(cfg, sleep_hint_enabled=False, sleep_hint_interval_s=0))


def test_owner_confirmed_needs_real_score(listener, cfg):
    assert listener.owner_confirmed([], 0, dict(cfg, speaker_verify_enabled=False)) is False
