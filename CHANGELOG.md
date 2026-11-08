# История

Все записи ниже — функциональная история ветки 3.x, без приватных логов и диалогов.

## Portable export (based on v3.12)
- Отдельный `src/`, portable runtime paths, `.venv`, нейтральный example config.
- Личные сценарии opt-in, отдельный credential namespace, никакой миграции live-данных.
- Документация, model-free pytest/CI, MIT, privacy guardrails и pinned direct dependencies.
- Это source export, не автоматическая переустановка работающего экземпляра.

## v3.12 — Надёжность
- User-level supervisor, singleton mutex, intentional stop, crash-loop backoff.
- Scoped Windows Credential Manager и локальный fallback; таблицы pytest.

## v3.11 — Проактивность
- Queued proactive outbox, expiry, quiet hours, persistent DND/dedup.
- Calendar, configurable training/protein reminders, presence morning webhook.
- Приоритет новой wake-команды; speaker verification только оценивалась, не включена.

## v3.10 — Быстрые команды
- Repeat/slower, stateful mute, volume, screenshot/disk/window/clipboard.
- Persistent timers/reminders, notes, Todoist/food/clipboard payload kinds.
- Focus/sleep/workout, read-only Git, shutdown с отдельным подтверждением.

## v3.9 — Скорость
- Per-request PERF metrics, sentence-level TTS pipeline, cached parallel ack.
- Watchdog + polling fallback, bounded template cache, background warmup, fuzzy router.

## v3.8 — Статус и речь
- Единые ударения local/webhook, падежи чисел и status vocabulary.
- Dated stale-cache reading и устранение повторяющихся waiting fillers.

## v3.5–3.7 — Разговор
- Local small talk, natural status aliases, улучшение capture/stop ack.
- Follow-up после речи, echo/confidence guards, словарь разговорного произношения.

## v3.0–3.4 — Основа
- Vosk, wake/claps, offline TTS/FX, локальные aliases, webhook/outbox replies.
