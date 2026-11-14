"""Single list of every voice command: what it does, how to say it, and where it is handled.

The matchers (jarvis.core.quick.match, jarvis.core.tasks.intent, the aliases in jarvis.app.settings, ...) stay
where they are; this registry is the documentation and «что ты умеешь» source, and the tests
keep it honest: every example must route to its command id and every command the matchers can
return must be listed here. docs/COMMANDS.md carries a generated copy (scripts/gen_commands_doc.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Command:
    id: str            # route id, see route_id()
    category: str
    summary: str       # what it does, one short line
    examples: Tuple[str, ...]


CATEGORIES: Tuple[Tuple[str, str], ...] = (
    ("day", "Задачи и день"),
    ("food", "Питание"),
    ("time", "Таймеры и время"),
    ("pc", "Компьютер"),
    ("media", "Звук и музыка"),
    ("text", "Буфер обмена и код"),
    ("dev", "Проекты и серверы"),
    ("modes", "Режимы"),
    ("talk", "Разговор"),
)

# Spoken by «что ты умеешь»: one clause per category, short on purpose.
CAPABILITIES = ("статус, задачи, что осталось, брифинг и проекты в Notion",
                "дневник еды и белок",
                "таймеры, напоминания, время и тренировки",
                "звук, экран, окна, программы и скриншоты",
                "буфер обмена: перевод, пересказ, ошибки",
                "серверы, тесты и гит",
                "режимы фокуса, тренировки, тишины и сна")

COMMANDS: Tuple[Command, ...] = (
    Command("status", "day", "Полный статус: еда, встречи, задачи, проекты", ("статус", "отчёт", "сводка")),
    Command("task_status", "day", "Коротко о задачах и встречах на сегодня", ("статус по задачам", "что у меня на сегодня", "какие у меня задачи")),
    Command("today", "day", "Планы на сегодня", ("какие планы", "планы на сегодня")),
    Command("tasks_all", "day", "Все задачи на сегодня и просроченные, каждая со временем", ("перескажи все задачи", "задачи все перескажи", "все задачи")),
    Command("tasks_left", "day", "Что ещё осталось сделать сегодня (и по Notion)", ("что ещё осталось", "чё ещё осталось", "что ещё надо сделать")),
    Command("tasks_briefing", "day", "Утренний брифинг по запросу", ("утренний брифинг", "брифинг")),
    Command("tasks_notion", "day", "Что осталось по каждому проекту в Notion", ("что по ноушену", "задачи по проектам")),
    Command("deploy", "dev", "Сводка по проектам и деплою", ("как деплой", "что по проектам")),
    Command("dated_query", "day", "Вопрос о другом дне уходит на сервер", ("какие задачи на завтра",)),
    Command("food", "food", "Сводка питания из кэша", ("сколько калорий", "что по еде")),
    Command("q:nutrition_left", "food", "Сколько осталось до нормы белка или калорий", ("сколько осталось белка", "сколько осталось до нормы белка")),
    Command("q:food_log", "food", "Записать еду в дневник", ("добавь двести грамм творога",)),
    Command("time", "time", "Который час", ("который час", "сколько времени")),
    Command("workout", "time", "Когда следующая тренировка", ("когда тренировка", "во сколько тренировка", "когда следующая тренировка")),
    Command("q:timer", "time", "Таймер", ("поставь таймер на пять минут",)),
    Command("q:reminder", "time", "Повторяющееся напоминание", ("напоминай каждые двадцать минут пить воду",)),
    Command("q:timer_cancel", "time", "Отменить таймеры и напоминания", ("отмени таймер",)),
    Command("jarvis_sleep", "modes", "Спящий режим на время", ("спящий режим на час", "засни на полчаса")),
    Command("q:mode", "modes", "Режимы фокуса, тренировки и сна (блокировка)", ("режим фокуса", "режим тренировки", "режим сна")),
    Command("cheatsheet_show", "modes", "Шпаргалка поверх экрана: протоколы и главные команды (или Ctrl+Alt+J)", ("покажи шпаргалку",)),
    Command("cheatsheet_hide", "modes", "Убрать шпаргалку", ("убери шпаргалку", "спрячь шпаргалку")),
    Command("proactive_dnd", "modes", "Не беспокоить", ("не беспокоить", "можно беспокоить")),
    Command("protocol_спящая_красавица", "modes", "Протокол «Спящая красавица»: пауза, сон до будильника или на срок, без повтора отбоя",
            ("протокол спящая красавица", "протокол спящая царевна", "протокол спящая красавица на шесть часов")),
    Command("protocol_негры_пашут", "modes", "Протокол «Негры пашут»: программы из workspace и режим фокуса", ("протокол негры пашут",)),
    Command("protocol_бобик_сдох", "modes", "Протокол «Бобик сдох»: конец работы — закрыть окна кроме защищённых, пауза, блокировка",
            ("протокол бобик сдох",)),
    Command("protocol_взлом_пентагона", "modes", "Протокол «Взлом Пентагона»: зелёные окна с безопасными командами", ("протокол взлом пентагона",)),
    Command("protocol_list", "modes", "Какие есть протоколы", ("какие протоколы", "список протоколов")),
    Command("protocol_cancel", "modes", "Отменить протокол: закрыть окна «взлома», снять тишину и сон", ("отмена протокола", "отмени протокол")),
    Command("monitor_off", "pc", "Выключить экран (без блокировки)", ("выключи экран", "выруби экран", "погаси экран")),
    Command("lock", "pc", "Заблокировать компьютер", ("заблокируй экран", "заблокируй компьютер")),
    Command("q:screenshot", "pc", "Скриншот", ("сделай скриншот",)),
    Command("q:close_window", "pc", "Закрыть активное окно", ("закрой окно",)),
    Command("q:disk", "pc", "Свободное место на диске", ("место на диске",)),
    Command("battery", "pc", "Заряд батареи", ("сколько заряда", "батарея")),
    Command("temperature", "pc", "Температура процессора", ("какая температура",)),
    Command("q:shutdown_prepare", "pc", "Выключить ноутбук через время, с подтверждением", ("выключи компьютер через десять минут",)),
    Command("q:shutdown_cancel", "pc", "Отменить выключение", ("отмени выключение",)),
    Command("browser", "pc", "Открыть браузер", ("открой браузер",)),
    Command("youtube", "pc", "Открыть YouTube", ("открой ютуб",)),
    Command("github", "pc", "Открыть GitHub проекта", ("открой гитхаб",)),
    Command("project", "pc", "Открыть проект", ("открой проект джарвис",)),
    Command("cursor", "pc", "Открыть Cursor", ("открой курсор",)),
    Command("telegram", "pc", "Открыть Telegram", ("открой телеграм",)),
    Command("vol_up", "media", "Громче", ("громче",)),
    Command("vol_down", "media", "Тише", ("тише",)),
    Command("q:volume", "media", "Громкость в процентах", ("громкость пятьдесят",)),
    Command("q:mute", "media", "Выключить или вернуть звук", ("выключи звук", "включи звук")),
    Command("play", "media", "Пауза и продолжить", ("пауза", "продолжи")),
    Command("next", "media", "Следующий трек", ("дальше", "следующий")),
    Command("prev", "media", "Предыдущий трек", ("назад", "предыдущий")),
    Command("q:repeat", "talk", "Повторить последний ответ", ("повтори", "помедленнее")),
    Command("q:clipboard_read", "text", "Прочитать буфер обмена", ("прочитай буфер",)),
    Command("q:clipboard_translate", "text", "Перевести буфер обмена", ("переведи буфер",)),
    Command("q:clipboard_summary", "text", "Кратко пересказать буфер обмена", ("кратко перескажи буфер",)),
    Command("q:explain_error", "text", "Объяснить ошибку из буфера или с экрана", ("объясни эту ошибку",)),
    Command("q:note", "text", "Записать идею в заметки", ("запиши идею купить молоко",)),
    Command("q:todoist_add", "day", "Добавить задачу в Todoist", ("добавь задачу купить хлеб",)),
    Command("q:confirm_in_chat", "dev", "Действие с подтверждением в чате: ветка, миграции, пул реквест", ("создай ветку для задачи логин",)),
    Command("q:server_health", "dev", "Проверить сервер", ("статус сервера",)),
    Command("q:project_tests", "dev", "Запустить тесты проекта", ("запусти тесты проекта джарвис",)),
    Command("q:git", "dev", "Последний коммит и состояние репозитория", ("последний коммит",)),
    Command("capabilities", "talk", "Что я умею", ("что ты умеешь", "что ты можешь")),
    Command("awake", "talk", "«Проснись», когда я и так не сплю", ("проснись",)),
    Command("stop", "talk", "Замолчать", ("стоп", "хватит", "замолчи")),
    Command("smalltalk", "talk", "Приветствия, спасибо, как дела", ("привет", "спасибо", "как дела")),
    Command("alarm_request", "time", "Будильник — через сервер", ("поставь будильник на семь",)),
)

BY_ID: Dict[str, Command] = {c.id: c for c in COMMANDS}


def route_id(alias: Optional[Dict[str, Any]]) -> Optional[str]:
    """Registry id of a matcher result."""
    if not alias:
        return None
    if alias.get("action") == "quick2":
        return "q:" + str(alias.get("cmd"))
    name = str(alias.get("name", ""))
    if name.startswith("chat_"):
        return "smalltalk"
    if name in ("dnd_on", "dnd_off"):
        return "proactive_dnd"
    return name or None


def capabilities_phrase() -> str:
    return "Умею вот что, сэр: " + "; ".join(CAPABILITIES) + ". Полный список команд я записал в журнал."


def by_category() -> List[Tuple[str, List[Command]]]:
    return [(title, [c for c in COMMANDS if c.category == key]) for key, title in CATEGORIES]


def render_markdown() -> str:
    out = ["<!-- registry:start (scripts/gen_commands_doc.py) -->", ""]
    for title, cmds in by_category():
        if not cmds:
            continue
        out += ["### " + title, "", "| Команда | Как сказать |", "|---|---|"]
        out += ["| %s | %s |" % (c.summary, ", ".join("«%s»" % e for e in c.examples)) for c in cmds]
        out.append("")
    out.append("<!-- registry:end -->")
    return "\n".join(out)


def log_lines() -> List[str]:
    return ["%s: %s" % (title, "; ".join(c.summary for c in cmds)) for title, cmds in by_category() if cmds]
