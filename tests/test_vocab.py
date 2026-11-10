import jarvis_vocab as V


def test_grammar_uses_model_spelling():
    assert V.vosk_spelling("Что ещё осталось?") == "что ещё осталось"
    assert V.vosk_spelling("что еще осталось") == "что ещё осталось"
    assert V.vosk_spelling("отчет") == "отчёт"
    assert V.vosk_spelling("перескажи все задачи") == "перескажу все задачи"


def test_norm_folds_yo():
    assert V.norm("Чё ЕЩЁ осталось?!") == "че еще осталось"


def test_listener_grammar_has_no_folded_only_words(listener, cfg):
    words = {w for p in listener.grammar_phrases(cfg) for w in p.split()}
    assert not words & set(V.VOSK_WORDS)
