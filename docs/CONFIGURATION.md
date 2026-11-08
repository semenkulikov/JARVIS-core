# Настройки

Скопировать `config.example.json` в `runtime/config.json`. Этот приватный файл не в Git.
`JARVIS_HOME` меняет корень runtime; `JARVIS_PROJECTS` — default каталог проектов.
Настройки перечитываются при изменении файла, но переключение моделей/микрофона лучше
делать с перезапуском. Неизвестные/несовместимые значения не имеют полного schema validation.

| Ключ | Default / назначение |
|---|---|
| `webhook_url` | Пусто: локальный режим; задать адрес собственного сервера только приватно |
| `webhook_auth_header` | Пусто; предпочтителен scoped Windows Credential Manager |
| `aliases` | Локальные фразы/actions; примеры уже включены, trusted configuration only |
| `projects_dir` | Пусто → `JARVIS_PROJECTS` или домашний `Projects`; никаких чужих путей |
| `mic_name_contains` | Пусто → default input device; подстрока имени микрофона |
| `tts_engine` / `silero_model` / `silero_speaker` | `silero` / `v5_6_ru` / `eugene` |
| `silero_rate` / `tts_threads` | `fast` / 3; CPU, не устанавливать тяжёлую GPU-конфигурацию без необходимости |
| `tts_chunk_chars` / `tts_gap_s` | 170 / 0.08; границы предложений сохраняются |
| `stress_ruaccent` / `ruaccent_model` | true / `tiny2.1`; первый запуск может скачивать модель |
| `stress_dict` / `phrase_rewrites` / `fx` | Дополнительные ударения, текстовые переписывания и параметры эффекта |
| `wake_word_enabled` / `oww_enabled` / `clap_enabled` | true; способы активации |
| `oww_threshold` / `vosk_wake_min_conf` | 0.5 / 0.80; выше — меньше ложных активаций |
| `min_conf` / `bargein_min_conf` | 0.55 / 0.60; у прерывания есть дополнительные guards |
| `grammar_hint` / `vosk_agc` | true; ограниченный command recognizer и auto gain |
| `wake_prebuffer_s` / `phrase_wait_s` | 1.6 / 1.5; сохранять начало, ждать начала речи |
| `phrase_silence_s` / `phrase_max_s` | 0.95 / 10; тишина завершает фразу с acoustic guard |
| `followup_window_s` / `followup_question_window_s` | 7 / 10; окно продолжения без wake |
| `followup_echo_guard_s` / `followup_min_conf` / `followup_max_turns` | 0.3 / 0.65 / 8; эхо, уверенность, предел серии |
| `outbox_watch_enabled` / `outbox_event_batch_s` | true / 0.02; event-driven watcher |
| `outbox_watch_rescan_s` / `outbox_poll_s` | 1 / 0.12; резервные scans и polling fallback |
| `fast_ack` / `ack_*` | Короткие заранее синтезируемые реплики; `ack_stop` не должен быть пустым |
| `intent_fuzzy_threshold` / `intent_fuzzy_margin` | 88 / 7; conservative local routing, не для произвольных OS actions |
| `template_precache` / `time_preload_minutes` | true / 3; bounded full-sentence templates |
| `cache_max_age_h` / `cache_stale_read_max_age_h` | 2.5 / 3; политика dated snapshot |
| `reply_timeout_s` / `wait_filler_s` | 240 / 12; после ack дополнительный filler не нужен |
| `clipboard_max_chars` / `clipboard_translate_target` | 8000 / `ru` |
| `shutdown_confirm_window_s` | 10; только отдельное `да/подтверждаю` из follow-up, confidence ≥0.8 |
| `focus_minutes` / `workout_set_minutes` / `workout_water_minutes` | 25 / 3 / 20; параметры режимов, не личное расписание |
| `workout_days` / `workout_time` | [] / `12:00`: расписание не задано, days Mon=0 |
| `workout_playlist_url` | Пусто; используется обычное media play |
| `proactive_quiet_start` / `proactive_quiet_end` | `23:00` / `08:00` |
| `proactive_min_interval_s` / `proactive_tick_s` | 120 / 5 |
| `proactive_training_enabled` / `proactive_training_weekdays` | false / []; явно настроить своё расписание |
| `proactive_training_time` | `12:00` — нейтральное неактивное значение; reminder за 15 min до тренировки |
| `proactive_calendar_enabled` / `proactive_calendar_lead_min` | true / 15; работает только с внешним events-кэшем |
| `proactive_protein_enabled` / `proactive_protein_time` | false / `18:00`; neutral opt-in |
| `proactive_protein_left_g` / `proactive_cache_max_age_h` | 60 / 3 |
| `morning_briefing_enabled` / `morning_start` / `morning_end` | false / `07:00` / `12:00` |
| `morning_idle_s` / `morning_max_attempts` / `morning_retry_s` | 14400 / 3 / 120 |
| `timezone` | Пусто → имя зоны ОС в payload; для сервера можно указать IANA label |

## Голос и произношение

Silero получает один и тот же pipeline для local и server replies:
числа/единицы/время → переписывания → optional RUAccent → explicit stress dictionary.
`+` стоит **перед ударной гласной**, например `уточн+яю`, `календар+е`, `пят+идесяти`,
`на св+язи`, `белк+а`. Покрываются падежи календаря/чисел, килокалории, граммы и статусные слова.
Кеш audio зависит от engine, speaker, словарей, rewrites и FX; при изменении параметров
получается новое cache key. Не обещается идеальная контекстная омография во всех фразах.

## Секреты

`JarvisVoiceAssistant.<credential-name>` / username `Jarvis` — отдельный namespace
Windows Credential Manager. Утилита `scripts/credentials.py` принимает значение скрытым вводом,
проверяет запись и никогда его не показывает. Запускайте в `.venv`.
Fallback: локальный config для webhook; environment / `FATSECRET_ENV_FILE` / runtime `.env`
для optional FatSecret. `config.legacy.json` и `.env.legacy` — совместимость старого
локального файла, всегда ignored. Backup-секреты в этот проект не переносятся.
Никогда не прикладывайте эти файлы к issue, PR или сообщению.
