import pytest

from jarvis.core import matching as M


def test_norm_phrase_folds_yo_and_punctuation():
    assert M.norm_phrase("Ещё, раз — всё!") == ["еще", "раз", "все"]
    assert M.norm_phrase(None) == []


@pytest.mark.parametrize("a,b,ok", [("тренировка", "тренировки", True), ("экран", "экран", True), ("батарея", "погода", False)])
def test_tok_match(a, b, ok):
    assert M.tok_match(a, b) is ok


@pytest.mark.parametrize("text,field", [("что там по делам", "today"), ("статус питания", "food"), ("статус по проектам", "deploy")])
def test_natural_status_alias_fields(text, field):
    assert M.natural_status_alias(text)["field"] == field


@pytest.mark.parametrize("text", ["отметь задачу выполненной", "добавь задачу в статус"])
def test_natural_status_alias_keeps_mutations_off_the_cache(text):
    assert M.natural_status_alias(text) is None


def test_pure_wait_filler():
    assert M.pure_wait_filler("Минуту, сэр, уточняю.")
    assert not M.pure_wait_filler("Сегодня две встречи.")


def test_followup_echo_matches_a_spoken_sentence():
    assert M.followup_echo("готово сэр", "Готово, сэр. Что-то ещё?")
    assert not M.followup_echo("да", "Да, сэр.")


def test_stop_needs_corroboration_without_negation(cfg):
    assert M.corroborated_stop("стоп", "стоп джарвис")
    assert not M.corroborated_stop("стоп", "не стоп")
    assert M.stop_candidate("Стоп", 0.9, False, cfg)
    assert not M.stop_candidate("стоп", 0.9, True, cfg)
