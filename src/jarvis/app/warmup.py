"""Background synthesis of the fixed phrases so the first replies play without a synthesis delay."""
from __future__ import annotations

import json
import logging
import os
import time

import jarvis_speed as SPEED
import jarvis_text as JT
from jarvis.adapters.process import trim_memory
from jarvis.adapters.tts import split_text
from jarvis.app.components import Components
from jarvis.app.conversation import (NO_REPLY_PHRASE, SEND_FAILED_PHRASE, SERVER_DOWN_PHRASE, SERVER_SLOW_PHRASE,
                                     TIMER_DONE_PHRASE)
from jarvis.core.phrases import all_phrases
from jarvis.core.ports import Config

log = logging.getLogger("jarvis")
FIXED_PHRASES = ("Блокирую, сэр.", TIMER_DONE_PHRASE, "Таймер отменён, сэр.", "Вебхук не настроен, сэр.", SEND_FAILED_PHRASE,
                 NO_REPLY_PHRASE, SERVER_DOWN_PHRASE, SERVER_SLOW_PHRASE, "Хорошо, сэр.", "Свежих данных нет, сэр, запрашиваю.",
                 "Не нашёл приложение, сэр.")
PRONUNCIATION_AUDIT = "pronunciation_audit_v312.json"


class Warmup:
    def __init__(self, c: Components) -> None:
        self.c = c

    def _stopping(self) -> bool:
        return os.path.exists(self.c.paths.stop_file)

    def run(self, cfg: Config) -> None:
        get_audio = self.c.voice.get_audio
        # Warm the first server ack before RUAccent has finished loading as well.
        try:
            get_audio(cfg.get("fast_ack", "Сейчас, сэр."), cfg)
            log.info("fast ack cache ready (initial)")
        except Exception as e: log.warning("fast ack warmup: %s", type(e).__name__)
        JT.init_accentizer(cfg, self.c.paths.home)
        cfg = self.c.config.load(); pronunciation_audit = []
        for t in all_phrases(cfg) + list(FIXED_PHRASES):
            pronunciation_audit.append({"text": t, "normalized": JT.normalize(t, cfg)})
            for _attempt in range(10):
                try:
                    for chunk in split_text(t, int(cfg.get("tts_chunk_chars", 170))): get_audio(chunk, cfg)
                    break
                except Exception as e: log.info("precache retry %s: %s", t, e); time.sleep(10)
        try:
            with open(os.path.join(self.c.paths.cache, PRONUNCIATION_AUDIT), "w", encoding="utf-8") as f:
                json.dump(pronunciation_audit, f, ensure_ascii=False, indent=2)
        except Exception as e: log.warning("pronunciation audit save failed: %s", type(e).__name__)
        log.info("precache done (%s, ruaccent=%s, audited_phrases=%d)", cfg.get("tts_engine"), JT.accent_state(), len(pronunciation_audit))
        if cfg.get("template_precache", True):
            templates = SPEED.template_phrases(cfg, JT)
            busy = self.c.signals.busy
            for phrase in templates:
                if self._stopping(): break
                # Do not queue background synthesis ahead of an active conversation.
                while busy.is_set() and not self._stopping(): time.sleep(0.1)
                if self._stopping(): break
                try: get_audio(phrase, cfg)
                except Exception as e: log.info("template cache skipped: %s", type(e).__name__)
            log.info("template precache done (%d bounded time/number sentences)", len(templates))
        trim_memory()
