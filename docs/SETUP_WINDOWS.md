# Установка на Windows без admin

## Предпосылки

Windows 10/11, Python 3.12 x64, микрофон/динамики, свободное место для моделей.
Полный listener Windows-specific; Linux CI проверяет только model-free логику.
Выберите любую рабочую папку проекта; пути к исходному компьютеру не зашиты.
Не запускайте вторую копию рядом с уже работающим голосовым ассистентом.

## Окружение и config

Из корня проекта в PowerShell 5 (команды отдельными строками, без `&&`):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
New-Item -ItemType Directory -Force .\runtime | Out-Null
Copy-Item .\config.example.json .\runtime\config.json
```

Версии direct dependencies сняты с работающего Windows-окружения; это не полный
transitive lock. Для Torch указан официальный CPU index; test requirements отдельно,
чтобы CI не скачивал ML stack. Piper нужен только при явном выборе другого TTS engine:
`python -m pip install -r requirements-piper.txt`.

`JARVIS_HOME` можно установить перед запуском, чтобы хранить runtime вне проекта.
Тогда config/models/outbox/logs и stop-файл находятся именно там, а не в `runtime/`.
`projects_dir` настраивается отдельно, личное расписание по умолчанию отсутствует.

## Модели (в Git не входят)

Создать `runtime/models/`, затем:

1. С [официального каталога Vosk](https://alphacephei.com/vosk/models) скачать небольшую
   русскую модель и распаковать в `runtime/models/vosk-model-small-ru-.../`.
   Должен быть ровно один подходящий `vosk-model*` каталог: код выбирает первый.
2. С [официального Silero](https://github.com/snakers4/silero-models) получить совместимый
   `v5_6_ru.pt` → `runtime/models/silero/v5_6_ru.pt`. Название согласовать с `silero_model`.
   Загружать Torch packages только из доверенного источника: они могут содержать код.
3. По [openWakeWord](https://github.com/dscripka/openWakeWord) один раз скачать pre-trained
   assets (включая embedding/melspectrogram) в его package resources:

   ```powershell
   .\.venv\Scripts\python.exe -c "import openwakeword; openwakeword.utils.download_models()"
   ```

   Затем `hey_jarvis_v0.1.onnx` скопировать из
   `.venv/Lib/site-packages/openwakeword/resources/models/` в `runtime/models/`.
   Используется ONNX backend; остальные package feature assets остаются в `.venv`.
4. RUAccent `tiny2.1` может скачать свои weights при первом warmup; для полностью
   автономного последующего запуска заранее дождаться завершения загрузки.
5. Optional Piper: согласованный ONNX + JSON voice в `runtime/models/piper/`;
   по умолчанию не нужен. Лицензии всех weights проверяются отдельно от MIT проекта.

Первичная настройка/скачивание требует сети; распознавание и TTS после подготовки локальны.
Свободные AI-запросы всегда зависят от внешнего сервера.

## Сервер и secrets (необязательно)

Для локальных команд `webhook_url` можно оставить пустым.
Для AI заполнить локальный URL и сохранить **полное значение Authorization**:

```powershell
.\.venv\Scripts\python.exe .\scripts\credentials.py set webhook_auth_header
.\.venv\Scripts\python.exe .\scripts\credentials.py check webhook_auth_header
```

Ввод скрыт. Значение не передаётся аргументом командной строки.
Никакие чужие existing credentials автоматически не читаются/не мигрируют.
Для FatSecret аналогично задаются только собственные имена из CLI choices;
нужны четыре OAuth1 credentials и отдельное подключение сервиса. `fatsecret_call.py`
может использовать приватный runtime `.env`/environment как совместимый fallback.
Внешний writer/agent создаёт status/outbox по [контракту](PAYLOADS.md).
Серверные prompts/routines/аккаунты пользователь настраивает отдельно.

## Тесты и первый запуск

```powershell
.\run_tests.ps1
# Полный запуск далее слушает микрофон и МОЖЕТ говорить вслух:
wscript.exe .\start_jarvis.vbs
```

Все automated tests — SILENT: синтез заменён фикстурами, playback/HTTP/OS запрещены
или mocked, реальные буфер/окна/shutdown/volume не трогаются. Тестам модели не нужны.
Наличие зелёных unit tests не заменяет ручную проверку выбранного микрофона и моделей.

`start_jarvis.vbs` скрыто запускает supervisor через `.venv/Scripts/pythonw.exe`.
Чтобы запускать при входе в Windows, создать shortcut на этот VBS в своей
папке Startup (`Win+R` → `shell:startup`). Не копировать туда VBS с относительными
путями напрямую; shortcut должен указывать на файл внутри проекта.
Admin/служба не требуются; установка проекта сама автозапуск не меняет.

## Остановка, перезапуск и диагностика

```powershell
New-Item -ItemType File -Force .\runtime\stop | Out-Null
# Подождать штатного завершения worker и supervisor по logs/processes.
# Новый явный запуск очищает intentional stop и создаёт один worker:
wscript.exe .\start_jarvis.vbs
Get-Content .\runtime\logs\jarvis_voice.log -Tail 40
.\.venv\Scripts\python.exe .\scripts\latency_summary.py --last 20
```

При нестандартном `JARVIS_HOME` изменить путь stop/log соответственно.
Намеренный stop завершает supervisor; crash перезапускается с backoff 2–300 s.
Named mutex защищает от дублирования в рамках одного Windows user/session и runtime.
У venv могут отображаться launcher и worker как два процесса: это не обязательно
два listener. Считать worker по command line/родительству, не только имени python.

Логи могут содержать распознанные фразы и ответы: перед передачей третьим лицам
обезличивать. Опубликовать private репозиторий недостаточно для проверки privacy:
перед переходом в public повторить scan и проверить историю/commit metadata.
