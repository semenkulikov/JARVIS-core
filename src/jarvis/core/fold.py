"""One spelling for matching: lower case and «ё» as «е» (Vosk, typed text and configs mix both)."""
from __future__ import annotations


def fold(text: str | None) -> str:
    return (text or "").lower().replace("ё", "е")
