"""Configuration schema of this application: built-in aliases, defaults of every module, finalisation.

The generic loading, reloading and validation lives in :mod:`jarvis.core.config`.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from jarvis.core import codemode as CODE
from jarvis.core import quick as QUICK
from jarvis.adapters import credentials as CREDS
from jarvis.app import server_jobs as SERVER_JOBS
from jarvis.core import dialog as DIALOG
from jarvis.core import food as FOOD
from jarvis.core import gate as GATE
from jarvis.core import names as NAMES
from jarvis.core import cheatsheet as CHEATSHEET
from jarvis.core import protocols as PROTOCOLS
from jarvis.core import timetable as TIMETABLE
from jarvis.core import proactive as PROACTIVE
from jarvis.core import projects as PROJECTS
from jarvis.core import sleep as SLEEP
from jarvis.core import voiceprint as SPEAKER
from jarvis.core import text as JT
from jarvis.core.config import ConfigStore, merge_aliases
from jarvis.core.phrases import SMALLTALK_ALIASES

log = logging.getLogger("jarvis")

DEFAULT_ALIASES: list[dict[str, Any]] = [
    {"name": "status", "phrases": ["статус", "статус по задачам", "отчёт", "доклад", "сводка", "что по задачам"], "action": "status"},
    {"name": "food", "phrases": ["сколько белка", "сколько калорий", "что по еде", "что по питанию"], "action": "cache_field", "field": "food"},
    {"name": "today", "phrases": ["что сегодня", "какие планы", "планы на сегодня"], "action": "cache_field", "field": "today"},
    {"name": "deploy", "phrases": ["как деплой", "что по проектам", "что с деплоем"], "action": "cache_field", "field": "deploy"},
    {"name": "time", "phrases": ["который час", "время", "сколько времени"], "action": "time"},
    {"name": "stop", "phrases": ["заткнись", "замолкни", "замолчи", "шадап", "шат ап", "шатап", "хватит", "стоп", "тихо", "помолчи", "умолкни", "довольно", "отставить", "отмена"], "action": "stop"},
    {"name": "vol_up", "phrases": ["громче", "погромче", "сделай громче"], "action": "key", "key": "vol_up", "times": 5, "extra_words": 1},
    {"name": "vol_down", "phrases": ["тише", "потише", "сделай тише"], "action": "key", "key": "vol_down", "times": 5, "extra_words": 1},
    {"name": "mute", "phrases": ["без звука", "выключи звук", "верни звук", "включи звук"], "action": "key", "key": "mute", "times": 1, "extra_words": 1},
    {"name": "play", "phrases": ["пауза", "продолжи", "продолжай", "играй"], "action": "key", "key": "play", "times": 1, "silent": True, "extra_words": 0},
    {"name": "next", "phrases": ["дальше", "следующий", "следующая"], "action": "key", "key": "next", "times": 1, "silent": True, "extra_words": 0},
    {"name": "prev", "phrases": ["назад", "предыдущий", "предыдущая"], "action": "key", "key": "prev", "times": 1, "silent": True, "extra_words": 0},
    {"name": "monitor_off", "phrases": ["выключи экран", "погаси экран", "выключи монитор", "выруби экран", "выруби монитор", "отключи экран", "погаси монитор", "потуши экран"], "action": "monitor_off"},
    {"name": "timer_cancel", "phrases": ["отмени таймер", "отключи таймер", "убери таймер"], "action": "timer_cancel"},
    {"name": "timer", "phrases": ["таймер", "поставь таймер"], "action": "timer", "extra_words": 5},
    {"name": "battery", "phrases": ["заряд", "сколько заряда", "батарея"], "action": "battery", "extra_words": 1},
    {"name": "temperature", "phrases": ["температура", "какая температура"], "action": "temperature", "extra_words": 1},
    {"name": "browser", "phrases": ["открой браузер", "браузер"], "action": "open", "target": "https://www.google.com"},
    {"name": "youtube", "phrases": ["открой ютуб"], "action": "open", "target": "https://www.youtube.com"},
    {"name": "github", "phrases": ["открой гитхаб", "открой гит хаб"], "action": "open_github"},
    {"name": "project", "phrases": ["открой проект"], "action": "open_project", "extra_words": 6},
    {"name": "cursor", "phrases": ["открой курсор"], "action": "open", "target": "%LOCALAPPDATA%\\Programs\\cursor\\Cursor.exe"},
    {"name": "telegram", "phrases": ["открой телеграм", "открой телеграмм"], "action": "open", "target": "%APPDATA%\\Telegram Desktop\\Telegram.exe"},
    {"name": "lock", "phrases": ["заблокируй экран", "заблокируй компьютер", "блокировка"], "action": "lock", "reply": "Блокирую, сэр."},
    {"name": "workout", "phrases": ["когда тренировка", "тренировка", "во сколько тренировка", "когда следующая тренировка", "следующая тренировка"], "action": "workout"},
]



DEFAULTS: dict[str, Any] = {
    "webhook_url": "",
    "webhook_auth_header": "",
    "tts_engine": "silero", "silero_model": "v5_6_ru", "silero_speaker": "eugene", "silero_rate": "fast",
    "vosktts_speaker": 3, "piper_voice": "ruslan", "piper_length_scale": 0.85,
    "tts_chunk_chars": 170, "tts_gap_s": 0.08,
    "fast_ack": "Сейчас, сэр.", "outbox_watch_enabled": True, "outbox_event_batch_s": 0.02, "outbox_watch_rescan_s": 1.0, "outbox_poll_s": 0.12,
    "intent_fuzzy_enabled": True, "intent_fuzzy_threshold": 88, "intent_fuzzy_margin": 7, "intent_max_words": 8,
    "time_preload_minutes": 3, "template_precache": True,
    "clipboard_max_chars": 8000, "clipboard_translate_target": "ru", "repeat_silero_rate": "slow",
    "shutdown_confirm_window_s": 10.0, "focus_minutes": 25, "workout_set_minutes": 3, "workout_water_minutes": 20,
    "workout_playlist_url": "", "timer_max_s": 604800,
    "stress_ruaccent": True, "ruaccent_model": "tiny2.1", "ruaccent_dictionary": False, "ruaccent_tiny_mode": True,
    "wake_word_enabled": True, "oww_enabled": True, "oww_threshold": 0.5, "barge_in_threshold": 0.6,
    "vosk_wake_min_conf": 0.80,
    "followup_enabled": True, "followup_window_s": 7.0, "followup_question_window_s": 10.0,
    "followup_echo_guard_s": 0.3, "followup_min_conf": 0.65, "followup_max_turns": 8,
    "wake_prebuffer_s": 1.6, "phrase_wait_s": 1.5, "phrase_silence_s": 0.95, "phrase_silence_fast_s": 0.45, "phrase_max_s": 10.0, "followup_listen_s": 7.0,
    "ack_command": ["Есть, сэр.", "Как прикажете, сэр.", "Будет сделано, сэр.", "Слушаюсь, сэр.", "Сию минуту, сэр.", "Уже делаю, сэр."],
    "ack_free": ["Да, сэр.", "Слушаюсь, сэр.", "Секунду, сэр."],
    "ack_wait": ["Минуту, сэр, уточняю.", "Секунду, сэр.", "Почти готово, сэр."],
    "ack_not_understood": ["Простите, сэр, не расслышал. Повторите, пожалуйста."],
    "wait_filler_s": 12.0, "cache_stale_read_max_age_h": 3.0,
    "ack_status": ["Уточняю данные, сэр.", "Проверяю свежие данные, сэр."], "stop_phrases": ["заткнись", "замолкни", "замолчи", "шадап", "шат ап", "шатап", "хватит", "стоп", "тихо", "помолчи", "умолкни", "довольно", "отставить"], "ack_stop": ["Как скажете, сэр.", "Как прикажете.", "Умолкаю, сэр.", "Ладно, сэр."], "bargein_min_conf": 0.60, "min_conf": 0.55,
    "vosk_agc": True, "vosk_agc_max_gain": 12.0, "vosk_agc_target_peak": 0.6, "grammar_hint": True, "tts_threads": 3,
    "clap_enabled": True, "clap_min_peak": 0.2, "clap_ratio": 10.0, "clap_attack": 4.0, "clap_max_len_s": 0.15,
    "clap_decay": 0.25, "clap_gap_min_s": 0.12, "clap_gap_max_s": 0.9, "clap_quiet_s": 0.5, "clap_peak_similarity": 4.0,
    "clap_log_min_peak": 0.08, "clap_tail_s": 0.25, "clap_noise_rel": 0.35, "clap_noise_attack": 2.0,
    "cooldown_s": 1.0, "reply_timeout_s": 240, "server_notice_s": 90.0, "server_down_wait_s": 45.0, "server_down_ttl_s": 1800.0, "cache_max_age_h": 2.5, "cache_future_skew_min": 15.0,
    "workout_days": [], "workout_time": "12:00",
    "projects_dir": "",
    "level_log_interval_s": 300, "memory_log_interval_s": 1800, "memory_restart_mb": 4096, "memory_trim_idle_s": 900,
    "aliases": DEFAULT_ALIASES,
}

DEFAULTS.update(PROACTIVE.DEFAULTS)
DEFAULTS.update({k: v for k, v in GATE.DEFAULTS.items() if k not in DEFAULTS})
DEFAULTS.update({k: v for k, v in SPEAKER.DEFAULTS.items() if k not in DEFAULTS})
for _mod in (CODE, PROJECTS, FOOD, DIALOG, SLEEP, SERVER_JOBS, NAMES, TIMETABLE, PROTOCOLS, CHEATSHEET): DEFAULTS.update({k: v for k, v in _mod.DEFAULTS.items() if k not in DEFAULTS})


def read_local_protocols(cfg: dict[str, Any], home: str) -> Any:
    """The owner's gitignored protocol additions; None when absent. Its content is never logged."""
    name = str(cfg.get("protocols_local_file") or "")
    if not name: return None
    path = Path(home) / name
    if not path.is_file(): return None
    try: data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e: log.warning("local protocol file unreadable (%s); ignored", type(e).__name__); return None
    if not isinstance(data, dict): log.warning("local protocol file: an object expected; ignored"); return None
    return data


def finalize(cfg: dict[str, Any], home: str) -> None:
    """Values derived after loading: secrets, merged aliases, stress marks, process-wide text settings."""
    cfg["latin_words"] = JT.latin_words(cfg.get("latin_words"))
    cfg["webhook_auth_header"] = CREDS.webhook(cfg, home)
    cfg["protocols"] = PROTOCOLS.merge_local(cfg.get("protocols"), read_local_protocols(cfg, home))
    cfg["aliases"] = merge_aliases(cfg.get("aliases"), DEFAULT_ALIASES) + SMALLTALK_ALIASES + PROTOCOLS.aliases(cfg) + CHEATSHEET.aliases()
    cfg["stress_dict"] = dict(dict(PROACTIVE.STRESS, **QUICK.STRESS, **DIALOG.STRESS), **(cfg.get("stress_dict") or {}))


def config_store(home: str | Path) -> ConfigStore:
    home = str(home)
    return ConfigStore(os.path.join(home, "config.json"), DEFAULTS, lambda cfg: finalize(cfg, home))
