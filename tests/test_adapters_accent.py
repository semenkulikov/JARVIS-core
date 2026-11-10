from jarvis.adapters.accent import Accentizer
from jarvis.core import text as T


def test_unloaded_accentizer_leaves_text():
    a = Accentizer()
    assert a.state == "off" and a.apply("замок") == "замок"
    a.load({"stress_ruaccent": False}, "unused")
    assert a.state == "disabled"


def test_loaded_accentizer_runs_per_sentence_before_the_dictionary():
    a = Accentizer()
    seen = []
    a._obj = type("Fake", (), {"process_all": lambda self, p: seen.append(p) or p.replace("замок", "з+амок")})()
    out = T.normalize("Замок закрыт. Новый замок.", {}, accent=a.apply)
    assert seen == ["Замок закрыт.", "Новый замок."] and "з+амок" in out and a.last_ms is not None
