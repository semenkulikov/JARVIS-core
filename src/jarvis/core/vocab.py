"""Spelling bridge between our phrases and the Vosk small Russian model.

Matching always folds «ё» to «е» (see norm). The Vosk vocabulary, however, spells some words
only with «ё» («ещё», «отчёт») and lacks a few imperatives («перескажи»); a grammar that uses
the folded spelling silently loses those words. vosk_spelling() restores the model's spelling
for grammar phrases. Checked against vosk-model-small-ru-0.22.
"""
from __future__ import annotations

import re

# folded spelling -> the only spelling the model knows
VOSK_WORDS = {
    "еще": "ещё", "отчет": "отчёт", "отчеты": "отчёты", "учет": "учёт", "счет": "счёт", "идет": "идёт",
    "пойдем": "пойдём", "зеленые": "зелёные", "трех": "трёх", "четырех": "четырёх", "мое": "моё", "твое": "твоё",
    # imperatives missing from the vocabulary: the model hears the closest word it has
    "перескажи": "перескажу",
}


def norm(text: str) -> str:
    """Lower-case, «ё» -> «е», punctuation -> spaces, single spaces."""
    t = (text or "").lower().replace("ё", "е")
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def vosk_spelling(phrase: str) -> str:
    return " ".join(VOSK_WORDS.get(w, w) for w in norm(phrase).split())
