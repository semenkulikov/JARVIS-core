"""Wake names from one source (jarvis.core.names): new names, two-word names, priority and vocabulary."""
import logging

import pytest

from jarvis.core import gate as GATE
from jarvis.core import names as NAMES
from jarvis.core import proactive as PROACTIVE
from jarvis.core import sleep as SLEEP
from jarvis.core import wake as W
from jarvis.core.names import NameSet


def words(text, conf=1.0, start=0.0):
    out = []
    for i, w in enumerate(text.split()):
        out.append({"word": w, "conf": conf, "start": start + i * 0.4, "end": start + i * 0.4 + 0.3})
    return out


@pytest.mark.parametrize("said,command", [
    ("нубас громче", "громче"),
    ("кусок железа который час", "который час"),
    ("хей жестянка статус", "статус"),
    ("эй нуб пауза", "пауза"),
    ("железяка тише", "тише"),
    ("эй железка громче", "громче"),
    ("джарвис громче", "громче"),
    ("хей джарвис стоп", "стоп"),
])
def test_every_name_gives_the_command_without_the_name(said, command):
    assert W.strip_wake(said.split()) == command
    assert " ".join(w["word"] for w in W.strip_wake_words(words(said))) == command


def test_only_one_word_of_a_two_word_name_is_not_a_name():
    assert W.strip_wake("кусок хлеба".split()) == "кусок хлеба"
    assert W.strip_wake("железный кусок".split()) == "железный кусок"


def test_bare_two_word_name_counts_as_only_the_name():
    assert W.only_wake_heard(words("кусок железа"), "") and W.only_wake_heard([], "хей жестянка")
    assert not W.only_wake_heard(words("кусок"), "хлеба")


def test_name_closing_a_project_phrase_stays_the_argument():
    assert [w["word"] for w in W.strip_wake_words(words("открой проект нубас"))] == ["открой", "проект", "нубас"]


def test_free_transcript_confirms_two_word_names_only_whole_and_sure():
    names = NAMES.DEFAULT
    assert GATE.wake_word_confirmed(words("кусок железа"), 0.7, names, 0.85)
    assert not GATE.wake_word_confirmed(words("кусок железа", conf=0.8), 0.7, names, 0.85)  # stricter for new names
    assert GATE.wake_word_confirmed(words("джарвис", conf=0.8), 0.7, names, 0.85)
    assert not GATE.wake_word_confirmed(words("кусок"), 0.7, names, 0.85)


def test_priority_interrupt_stays_with_jarvis():
    assert set(W.PRIORITY_WAKE_WORDS) == set(PROACTIVE.WAKE_NAMES) and "нуб" not in W.PRIORITY_WAKE_WORDS
    assert PROACTIVE.priority_candidate("джарвис громче", 0.9, "", PROACTIVE.DEFAULTS)
    assert not PROACTIVE.priority_candidate("нуб громче", 0.9, "", PROACTIVE.DEFAULTS)


@pytest.mark.parametrize("phrase", ["нубас проснись", "проснись кусок железа", "хей жестянка проснись", "джарвис проснись"])
def test_any_name_wakes_from_sleep(phrase):
    assert SLEEP.is_wake_phrase(phrase) and SLEEP.is_hint_word(phrase.replace("проснись", "").replace("хей", "").strip())


def test_name_grammar_has_every_name_with_prefixes():
    g = NAMES.DEFAULT.grammar()
    for n in ("джарвис", "нуб", "нубас", "кусок железа", "жестянка", "железяка", "железка"):
        assert {n, "хей " + n, "эй " + n} <= set(g)
    assert g[-1] == "[unk]"


def test_flags_and_extra_names_from_config():
    cfg = {"wake_names": [{"name": "нуб", "enabled": False}, {"name": "нубас"}],
           "wake_names_extra": ["пятница", {"name": "бро", "enabled": False}]}
    names = NameSet.from_cfg(cfg)
    assert [n.text for n in names.names] == ["джарвис", "нубас", "пятница"]
    assert names.strip("пятница громче".split()) == ["громче"] and names.strip("нуб громче".split()) == ["нуб", "громче"]


def test_names_with_unknown_words_are_left_out():
    names = NameSet.from_cfg(NAMES.DEFAULTS, missing={"железяка", "нубас"})
    assert "железяка" not in names.grammar() and "железка" in names.grammar() and "нубас" not in names.grammar() and "джарвис" in names.grammar()


class Model:
    def __init__(self, missing): self.missing = missing
    def vosk_model_find_word(self, w): return -1 if w in self.missing else 7


def test_vocabulary_check_warns_once_and_keeps_jarvis(app, cfg, caplog):
    asr = app.c.asr; app.c.state.model = Model({"железяка", "сдох"})
    with caplog.at_level(logging.WARNING, logger="jarvis"):
        missing = asr.check_vocabulary(cfg, ["протокол бобик сдох"])
        asr.check_vocabulary(cfg, ["протокол бобик сдох"])
    assert missing == {"железяка", "сдох"}
    assert caplog.text.count("'железяка' is not in the Vosk model") == 1 and caplog.text.count("'сдох'") == 1
    assert "железяка" not in asr.names(cfg).grammar() and "джарвис" in asr.names(cfg).grammar()


@pytest.mark.parametrize("heard,conf,name,sure", [
    ("джарвис", 0.82, "джарвис", True),
    ("нубас", 0.82, "нубас", False),        # new names need wake_alias_min_conf (0.85)
    ("кусок железа", 0.9, "кусок железа", True),
    ("хей жестянка", 0.9, "жестянка", True),
])
def test_wake_grammar_hit(app, cfg, heard, conf, name, sure):
    ws, ok = app.c.asr.wake_hit(words(heard, conf), cfg)
    assert " ".join(w["word"] for w in ws) == name and ok is sure


def test_wake_grammar_without_a_name(app, cfg):
    assert app.c.asr.wake_hit(words("[unk]"), cfg) is None
