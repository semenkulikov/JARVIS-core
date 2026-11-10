# Настройки

Скопируйте `config.example.json` в `runtime/config.json`. Этот файл в Git не входит. `JARVIS_HOME` меняет корень рабочего каталога. `JARVIS_PROJECTS` задаёт каталог проектов, если `projects_dir` пуст. `JARVIS_LOG_DIR` и `JARVIS_SCREENSHOTS` переносят журналы и снимки экрана, `JARVIS_CREDENTIAL_PREFIX` меняет префикс записей в диспетчере учётных данных (по умолчанию `JarvisVoiceAssistant.`).

`config_version` — версия формата настроек. Файл без неё считается старой установкой: при загрузке применяются миграции из `src/jarvis_migrations.py` (сам файл не переписывается). `latin_words` — свои произношения латинских слов, например `{"mercusys": "меркусис"}`.

Файл перечитывается при сохранении. Модель и микрофон лучше менять с перезапуском. Тип каждого значения сверяется со значением по умолчанию (числа взаимозаменяемы, фразы — строка или список): несовпадение пишется в журнал строкой `config value …`, но значение всё равно применяется. Свои ключи не проверяются.

| Ключ | Что значит |
|---|---|
| `webhook_url` | Пусто — только локальные команды. Адрес своего сервера пишите только в этот файл |
| `webhook_auth_header` | Пусто. Лучше хранить значение в своей записи диспетчера учётных данных Windows |
| `aliases` | Локальные фразы и действия. Примеры уже в файле. Это ваши настройки, не данные извне. Запись с тем же `name`, что и встроенная, дополняет её фразы; `"replace": true` заменяет их полностью. Новые встроенные команды добавляются сами |
| `projects_dir` | Пусто → `JARVIS_PROJECTS` или домашний каталог `Projects` |
| `mic_name_contains` | Пусто — микрофон по умолчанию. Иначе подстрока имени устройства |
| `tts_engine` / `silero_model` / `silero_speaker` | `silero` / `v5_6_ru` / `eugene` |
| `silero_rate` / `tts_threads` | `fast` / 3. Считается на процессоре |
| `tts_chunk_chars` / `tts_gap_s` | 170 / 0,08. Границы предложений сохраняются |
| `stress_ruaccent` / `ruaccent_model` | true / `tiny2.1`. Первый запуск может скачать модель |
| `stress_dict` / `phrase_rewrites` / `fx` | Свои ударения, замены текста и параметры тембра |
| `wake_word_enabled` / `oww_enabled` / `clap_enabled` | true. Три способа активации |
| `oww_threshold` / `vosk_wake_min_conf` | 0,5 / 0,80. Выше — меньше ложных включений |
| `min_conf` / `bargein_min_conf` | 0,55 / 0,60. У прерывания есть ещё проверки |
| `grammar_hint` / `vosk_agc` | true. Узкий распознаватель команд и автоусиление |
| `wake_prebuffer_s` / `phrase_wait_s` | 1,6 / 1,5. Не потерять начало фразы и дождаться речи |
| `phrase_silence_s` / `phrase_max_s` | 0,95 / 10. Тишина кончает фразу, если звук это подтверждает |
| `followup_window_s` / `followup_question_window_s` | 7 / 10. Сколько секунд слушать без имени |
| `followup_echo_guard_s` / `followup_min_conf` / `followup_max_turns` | 0,3 / 0,65 / 8. Эхо, уверенность, длина серии |
| `outbox_watch_enabled` / `outbox_event_batch_s` | true / 0,02. Чтение `outbox` по событиям файлов |
| `outbox_watch_rescan_s` / `outbox_poll_s` | 1 / 0,12. Повторный обход и запасной опрос |
| `fast_ack` / `ack_*` | Короткие реплики, их можно синтезировать заранее. `ack_stop` не оставляйте пустым |
| `ack_wake` / `ack_action` / `ack_lookup` / `ack_food` / `ack_server` | Мгновенные отклики: на голое имя, на действие, на проверку, на запись еды, на запрос к серверу. Списки, одна и та же фраза подряд не звучит. Все синтезируются при запуске |
| `wake_ack_after_s` | 0,7. Пауза после голого «Джарвис», после которой звучит «Да, сэр?» |
| `intent_fuzzy_threshold` / `intent_fuzzy_margin` | 88 / 7. Осторожный локальный разбор. Не для произвольных действий системы |
| `template_precache` / `time_preload_minutes` | true / 3. Ограниченный набор целых фраз в кэше |
| `cache_max_age_h` / `cache_stale_read_max_age_h` | 2,5 / 3. До какого возраста читать снимок с датой |
| `reply_timeout_s` / `wait_filler_s` | 240 / 12. После первой реплики вторая «минуту» не нужна |
| `clipboard_max_chars` / `clipboard_translate_target` | 8000 / `ru` |
| `shutdown_confirm_window_s` | 10. Годится только отдельное «да» или «подтверждаю», уверенность не ниже 0,8 |
| `focus_minutes` / `workout_set_minutes` / `workout_water_minutes` | 25 / 3 / 20. Длины режимов, не личное расписание |
| `workout_days` / `workout_time` | [] / `12:00`. Расписание пустое. Понедельник — 0 |
| `workout_playlist_url` | Пусто. Тогда обычное «играй» |
| `proactive_quiet_start` / `proactive_quiet_end` | `23:00` / `08:00` |
| `proactive_min_interval_s` / `proactive_tick_s` | 120 / 5 |
| `proactive_training_enabled` / `proactive_training_weekdays` | false / []. Своё расписание задаётся явно |
| `proactive_training_time` | `12:00`, пока тренировки выключены. Напоминание за 15 минут |
| `proactive_calendar_enabled` / `proactive_calendar_lead_min` | true / 15. Работает только если сервер прислал события |
| `proactive_protein_enabled` / `proactive_protein_time` | false / `18:00`. Выключено, пока не включите |
| `proactive_protein_left_g` / `proactive_cache_max_age_h` | 60 / 3 |
| `morning_briefing_enabled` / `morning_start` / `morning_end` | false / `07:00` / `12:00` |
| `morning_idle_s` / `morning_max_attempts` / `morning_retry_s` | 14400 / 3 / 120 |
| `timezone` | Пусто — в запрос уходит имя пояса Windows. Можно указать имя IANA для сервера |

## Голос и ударения

И локальный ответ, и текст сервера проходят одну цепочку: числа, единицы и время, затем замены, затем RUAccent если он включён, затем явный словарь ударений.

Знак `+` стоит **перед ударной гласной**: `уточн+яю`, `календар+е`, `пят+идесяти`, `на св+язи`, `белк+а`. Словарь покрывает падежи календаря и чисел, килокалории, граммы и слова статуса. Кэш звука зависит от движка, голоса, словарей, замен и тембра. Сменили параметр — получится новый ключ кэша. Одинаковые написания с разным ударением словарь сам не различает: ударение задаётся явно.

## Код, проекты и питание

| Ключ | По умолчанию |
|---|---|
| `explain_error_ocr` / `explain_error_max_chars` | true / 6000. OCR активного окна, только если буфер пуст |
| `servers` | []. Пример: `[{"name": "site", "spoken": ["сайт"], "url": "https://example.com/health"}, {"name": "router", "spoken": ["роутер"], "host": "192.168.0.1", "port": 80}]` |
| `health_timeout_s` | 5 |
| `projects` | {}. Пример: `{"demo": {"path": "C:/Projects/demo", "spoken": ["демо"], "test_command": ["python", "-m", "pytest", "-q"], "timeout_s": 600}}` — только список аргументов |
| `tests_timeout_s` | 900 |
| `food_local_enabled` | false. Включает запись еды напрямую в FatSecret |
| `food_alias_file` | `cache/food_aliases.json`. Заполняется `scripts/food_alias.py` |
| `food_dedupe_s` / `food_max_grams` | 180 / 3000. Повтор той же записи в этом окне не создаётся |
| `nutrition_targets` | {}. Например `{"calories": 2500, "protein_g": 120}` |

Словарь продуктов: `python scripts/food_alias.py --home <каталог> add --food-id <id> --names творог,творога`. Скрипт читает продукт из FatSecret и берёт порцию «100 г» или «100 мл». Для штук добавьте `--piece-g 50`. Запись в дневник идёт так: чтение дневника, одна попытка записи, чтение снова. После сбоя связи запись не повторяется, а ищется в дневнике.

## Распознавание команд

| Ключ | По умолчанию |
|---|---|
| `grammar_command_rescue` | true. Вариант грамматики принимается для безопасных команд, когда свободный текст на него похож |
| `grammar_rescue_min_ratio` | 0.6 |

Замеры — в [сравнении распознавателей](ASR_EVALUATION.md).

## Проверка голоса владельца

Необязательная проверка, выключена по умолчанию. Срабатывает после подтверждения имени и после сильного сигнала openWakeWord. Модель WeSpeaker ResNet34 в формате ONNX (26,5 МБ) работает локально на CPU в один поток.

| Ключ | По умолчанию |
|---|---|
| `speaker_verify_enabled` | false |
| `speaker_model` | `models/speaker/voxceleb_resnet34_LM.onnx` |
| `speaker_profile` | `speaker/profile.json` |
| `speaker_threshold` | Пусто. Тогда порог из профиля (0,35–0,6) |
| `speaker_window_s` / `speaker_min_audio_s` | 2.0 / 0.8 |
| `sleep_hint_enabled` / `sleep_hint_interval_s` | true / 600. Подсказка «как разбудить» на голое «Джарвис» во сне. Только при включённой проверке и узнанном голосе |

Запись голоса: `python scripts/enroll_speaker.py --home <каталог> --download`. Скрипт скачает модель и проверит SHA-256, на время записи приостановит запущенного помощника и потом запустит снова (`--keep-listener` — не трогать), запишет шесть нейтральных фраз без команд, сохранит профиль и выведет порог. Проверку он не включает. Если модели или профиля нет, проверка пропускается и в журнал пишется одна запись.

## Секреты

Запись называется `JarvisVoiceAssistant.<имя>`, пользователь записи — `Jarvis`. Это отдельная группа в диспетчере учётных данных Windows. `scripts/credentials.py` принимает значение скрытым вводом, проверяет запись и само значение не печатает. Запускайте её из `.venv`.

Если записи нет, заголовок `Authorization` берётся из локального `config.json`. Для FatSecret — из переменных окружения, `FATSECRET_ENV_FILE` или `.env` в рабочем каталоге. `config.legacy.json` и `.env.legacy` оставлены для старого локального файла и в Git не попадают. Старые копии секретов этот проект сам не переносит. Эти файлы не прикладывайте к задаче, запросу на слияние и письму.
