# Участие

Замечания и запросы на слияние можно писать по-русски или по-английски.

## Тесты

```powershell
python -m pip install -r requirements-test.txt
python -m pytest -q
```

Тесты не открывают микрофон, не ходят в сеть и не трогают громкость, буфер обмена, окна и выключение.

## Что не коммитить

Каталог `runtime/`, модели, журналы, снимки экрана, заметки и секреты. Пример настроек для репозитория — `config.example.json`. В задачу и запрос на слияние не прикладывайте `config.json` и журналы с распознанными фразами.

## Код

Новые модули пишите по PEP 8, с аннотациями типов. Проверка:

```powershell
python -m pip install ruff
python -m ruff check src tests scripts
```

Пакет `src/jarvis/` проверяется mypy (настройки в `pyproject.toml`, как в CI):

```powershell
python -m pip install mypy==1.13.0
python -m mypy
```

Настройки ruff и номер версии — в `pyproject.toml`. Перед запросом на слияние тесты должны проходить.

Новая голосовая команда — модуль в `src/jarvis/commands/` с обработчиком `@handles("действие")`,
запись в `src/jarvis/commands/catalog.py` и тест с `tests/command_fakes.FakeServices`; цикл слушателя и
разговор менять не нужно. Слои и направление импортов описаны в `docs/ARCHITECTURE.md`.
