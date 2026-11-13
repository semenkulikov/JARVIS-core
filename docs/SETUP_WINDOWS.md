# Установка на Windows

## Что нужно

Windows 10 или 11, Python 3.12 (64 бита), микрофон и колонки, место под модели. Права администратора не нужны. Прослушивание микрофона работает только в Windows. На Linux проверка на GitHub гоняет ту же логику без моделей и без звука.

Каталог проекта может быть любым: пути чужого компьютера в код не зашиты. Вторую копию рядом с уже говорящим помощником не запускайте.

## Окружение и настройки

Из корня проекта в PowerShell 5. Команды по одной строке, без `&&`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
New-Item -ItemType Directory -Force .\runtime | Out-Null
Copy-Item .\config.example.json .\runtime\config.json
```

В `requirements.txt` записаны прямые пакеты с проверенного окружения Windows. Вложенные зависимости туда не раскрыты. Для Torch указан официальный указатель сборок под процессор. Тестовые пакеты лежат отдельно, чтобы проверка на GitHub не качала модели и Torch.

Piper нужен только если в настройках выбран этот синтез: `python -m pip install -r requirements-piper.txt`.

Переменная `JARVIS_HOME`, заданная до запуска, переносит рабочий каталог из `runtime/` в другое место. Там же окажутся настройки, модели, `outbox`, журналы и файл `stop`. Каталог проектов задаётся отдельно. Своё расписание тренировок по умолчанию пустое.

## Модели

В Git их нет. Создайте `runtime/models/`.

1. С [каталога Vosk](https://alphacephei.com/vosk/models) скачайте небольшую русскую модель и распакуйте в `runtime/models/vosk-model-small-ru-.../`. Каталог `vosk-model*` должен быть один: код берёт первый.
2. С [репозитория Silero](https://github.com/snakers4/silero-models) возьмите `v5_6_ru.pt` и положите в `runtime/models/silero/v5_6_ru.pt`. Имя файла должно совпадать с ключом `silero_model`. Пакеты Torch берите только оттуда: внутри может быть код.
3. По инструкции [openWakeWord](https://github.com/dscripka/openWakeWord) один раз скачайте файлы модели, включая эмбеддинг и мел-спектрограмму, в ресурсы пакета:

   ```powershell
   .\.venv\Scripts\python.exe -c "import openwakeword; openwakeword.utils.download_models()"
   ```

   Затем скопируйте `hey_jarvis_v0.1.onnx` из `.venv/Lib/site-packages/openwakeword/resources/models/` в `runtime/models/`. Используется ONNX. Остальные служебные файлы пакета остаются в `.venv`.
4. RUAccent `tiny2.1` при первом запуске может сам скачать свои файлы. Дождитесь конца загрузки, если дальше компьютер должен работать без сети.
5. Piper по желанию: согласованные файлы ONNX и JSON в `runtime/models/piper/`. По умолчанию он не используется. Лицензии моделей не входят в MIT этого репозитория.

Первое скачивание требует сети. После этого распознавание и синтез идут локально. Свободные вопросы по-прежнему ходят на ваш сервер.

## Сервер и секреты

Для одних только локальных команд оставьте `webhook_url` пустым. Для свободных вопросов впишите адрес своего сервера и сохраните **полное значение заголовка Authorization**:

```powershell
.\.venv\Scripts\python.exe .\scripts\credentials.py set webhook_auth_header
.\.venv\Scripts\python.exe .\scripts\credentials.py check webhook_auth_header
```

Ввод скрыт. Значение не передаётся аргументом командной строки. Чужие уже сохранённые пароли программа не читает и не переносит.

Для FatSecret задаются только четыре своих ключа OAuth1 из списка команды. `fatsecret_call.py` может взять их из переменных окружения или из файла `.env` в рабочем каталоге. Внешняя программа пишет статус и ответы в `outbox` по [контракту](PAYLOADS.md). Промпты и учётные записи сервера настраиваются отдельно, в этот репозиторий они не входят.

## Тесты и первый запуск

```powershell
.\run_tests.ps1
wscript.exe .\start_jarvis.vbs
```

Тесты подменяют синтез и запрещают воспроизведение, сеть и действия системы. Модели им не нужны. Первый живой запуск слушает микрофон и может говорить вслух: проверьте выбранный микрофон и модели сами.

`start_jarvis.vbs` без окна запускает наблюдателя через `.venv/Scripts/pythonw.exe`. Чтобы помощник стартовал при входе в Windows, положите ярлык на этот VBS в свою папку автозагрузки (`Win+R`, затем `shell:startup`). Сам VBS туда не копируйте: внутри относительные пути. Ярлык должен указывать на файл в каталоге проекта. Служба и права администратора не нужны. Установка сама автозагрузку не меняет.

## Остановка и журнал

```powershell
New-Item -ItemType File -Force .\runtime\stop | Out-Null
wscript.exe .\start_jarvis.vbs
Get-Content .\runtime\logs\jarvis_voice.log -Tail 40
.\.venv\Scripts\python.exe .\scripts\latency_summary.py --last 20
```

После файла `stop` дождитесь, пока рабочий процесс и наблюдатель закончат работу. Следующий запуск снимает эту остановку и поднимает один процесс. Если задан `JARVIS_HOME`, файл `stop` и журнал ищите там.

Намеренная остановка гасит и наблюдателя. Падение процесса приводит к перезапуску с паузой от 2 до 300 секунд. Именованная блокировка не даёт запустить вторую копию тому же пользователю Windows в том же сеансе и том же рабочем каталоге. У виртуального окружения могут быть видны два процесса Python: запускатель и рабочий процесс. Это не два слушателя. Смотрите командную строку и родителя, а не только имя `python`.

В журнале бывают распознанные фразы и ответы. Перед тем как отдать журнал другому человеку, вычистите их. Перед тем как открыть репозиторий всем, просмотрите дерево файлов и историю коммитов.

## Перезапуск одной командой

Плановый перезапуск — это та же остановка файлом `stop` и новый запуск. Его удобно положить в маленький скрипт и задачу планировщика, чтобы перезапускать помощника одной командой, в том числе удалённо и без окон. Пример скрипта (пути замените на свои, `<JARVIS_HOME>` — рабочий каталог, `<checkout>` — каталог со `start_jarvis.vbs`):

```powershell
# restart_jarvis.ps1
$home_ = "<JARVIS_HOME>"; $start = "<checkout>\start_jarvis.vbs"
New-Item -ItemType File -Force "$home_\stop" | Out-Null
$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline -and (Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'jarvis_(supervisor|voice)\.py' })) { Start-Sleep 1 }
Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'jarvis_(supervisor|voice)\.py' } | % { Stop-Process -Id $_.ProcessId -Force }
Start-Process wscript.exe -ArgumentList "`"$start`""
```

Задача запускается от своего пользователя в интерактивном сеансе и без повышенных прав, иначе помощник не услышит микрофон и не покажет шпаргалку:

```powershell
schtasks /Create /TN JarvisRestart /SC ONCE /ST 00:00 /RL LIMITED /IT /F /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File <путь>\restart_jarvis.ps1"
schtasks /Run /TN JarvisRestart
```

Скрипт принудительно завершает только оставшиеся процессы `jarvis_supervisor.py` и `jarvis_voice.py`. После перезапуска в журнале появляется строка `listening (vX.Y.Z)` с номером версии. Окно PowerShell может мелькнуть; чтобы его не было, запускайте скрипт через короткий VBS с `WScript.Shell.Run …, 0`.

## Запуск из checkout при существующем рабочем каталоге

Если настройки, модели и журналы уже лежат в другом месте, код можно запускать прямо из клона репозитория. `scripts/deploy_home.py` пишет в рабочий каталог `start_jarvis.vbs`, который задаёт `JARVIS_HOME` и остальные переменные и запускает `src/jarvis_supervisor.py` из клона. Первый прежний `start_jarvis.vbs` сохраняется как `start_jarvis.vbs.pre-repo`.

```powershell
.\.venv\Scripts\python.exe scripts\deploy_home.py --home D:\Jarvis --python D:\Jarvisenv\Scripts\pythonw.exe --env JARVIS_LOG_DIR=D:\Jarvis\logs --restart
```

С `--restart` скрипт останавливает помощника файлом `stop`, запускает новый ярлык и ждёт строку `listening` в журнале. Если её нет 90 секунд, возвращается прежний ярлык. Обновление кода после этого — обычный `git pull` и перезапуск.

