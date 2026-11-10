"""Quick commands, pure part: phrase to action parsing, spoken durations and the grammar rescue rule.

Execution is jarvis.commands.controller; nothing here touches the system.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Mapping

from jarvis.core import codemode as CODE
from jarvis.core import food as FOOD
from jarvis.core import projects as PROJECTS
from jarvis.core import text as jt
from jarvis.core.numbers import duration, norm, number

__all__ = ["CACHED_REPLIES", "GRAMMAR_SAFE", "PHRASES", "STRESS", "duration", "duration_label", "grammar_rescue", "match", "norm", "number"]

PHRASES=CODE.PHRASES+PROJECTS.PHRASES+FOOD.PHRASES+['повтори','повтори ответ','еще раз','помедленнее','еще раз помедленнее','повтори помедленнее','что ты сказал','включи звук','верни звук','выключи звук','без звука','сделай скриншот','снимок экрана','скриншот','сделай снимок экрана','сколько свободно на диске','свободное место на диске','закрой окно','закрой активное окно','прочитай буфер','прочитай буфер обмена','переведи буфер','кратко перескажи буфер','отмени выключение','отмена выключения','отключи выключение','отмени таймер','отключи таймер','убери таймер','отмени напоминания','отключи напоминания','отмени все таймеры и напоминания','режим фокуса','режим сна','режим тренировки']

CACHED_REPLIES = ["Звук включён, сэр.","Скриншот сохранён, сэр.","Буфер обмена пуст, сэр.","Идея записана, сэр.","Отправил запрос на закрытие окна, сэр.","Выключение отменено, сэр.","Запланированного выключения нет, сэр.","Выключение не подтверждено, сэр.","Не удалось выполнить команду, сэр.","Пока нечего повторить, сэр.","Назовите проект полной командой, сэр.","Назовите громкость от нуля до ста процентов, сэр.","Назовите полный интервал таймера, сэр.","Активных таймеров или напоминаний нет, сэр.","Режим сна, сэр. Гашу экран и блокирую ноутбук.","Режим тренировки, сэр. Музыка, таймер подхода и напоминание о воде.","Сэр, пора выпить воды.","Сэр, время сделать перерыв."]
STRESS = {w.replace("+",""):w for w in ["гр+омкость","скринш+от","б+уфер","обм+ена","п+олный","п+олной","интерв+ал","напомин+ание","напомин+ания","напомин+аний","сохранен+о","своб+одно","гигаб+айта","д+иске","отпр+авил","закр+ытие","окн+а","подтвержд+аете","подтвержд+аю","подтвержден+о","выключ+ение","в+ыключить","д+анные","м+огут","пот+еряны","скаж+ите","зад+ержку","с+уток","отменен+о","ф+окуса","м+узыка","п+аузе","гаш+у","ноутб+ук","тренир+овки","подх+ода","перер+ыв","в+ыпить","вод+ы","ид+ея","зап+исана","повтор+ить","н+ечего","уд+алось","ком+анду","ком+андой","реж+им","нул+я","т+аймера","+или","заплан+ированного","пол+учено","вод+е","выключ+ения","в+ыполнить","назов+ите","пор+а","сд+елать"]}

SPECIAL_SPANS: dict[int, str] = {60:'минуту',90:'полторы минуты',1800:'полчаса',3600:'час',5400:'полтора часа',1:'секунду'}
def duration_label(secs: float) -> str:
    """Span after «на» / «через», as people say it: «час», «полтора часа», «два часа», «сорок пять минут»."""
    secs=int(secs)
    if secs in SPECIAL_SPANS:return SPECIAL_SPANS[secs]
    h,rest=divmod(secs,3600);m,s=divmod(rest,60);parts=[]
    if h:parts.append('час' if h==1 else jt.num_ru(h)+' '+jt.plural(h,'час','часа','часов'))
    if m:parts.append(jt.num_ru(m,'f')+' '+jt.plural(m,'минуту','минуты','минут'))
    if s:parts.append(jt.num_ru(s,'f')+' '+jt.plural(s,'секунду','секунды','секунд'))
    return ' '.join(parts)

def match(text: str, cfg: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    t=norm(text).strip(' .');cfg=cfg or {}
    def a(cmd: str, **kw: Any) -> dict[str, Any]: return {'name':'quick_'+cmd,'action':'quick2','cmd':cmd,**kw}
    sub=CODE.match(t) or PROJECTS.match(t) or FOOD.match(t,cfg)
    if sub:return sub
    if t in ('повтори','повтори ответ','еще раз','что ты сказал'):return a('repeat',slow=False)
    if t in ('помедленнее','еще раз помедленнее','повтори помедленнее','говори медленнее'):return a('repeat',slow=True)
    if t in ('включи звук','верни звук'):return a('mute',muted=False)
    if t in ('выключи звук','без звука'):return a('mute',muted=True)
    m=re.fullmatch(r'(?:поставь |сделай )?громкость(?: на)? (.+?)(?: процентов)?',t)
    if m:return a('volume',value=number(m[1]))
    if t in ('сделай скриншот','снимок экрана','скриншот','сделай снимок экрана'):return a('screenshot')
    m=re.fullmatch(r'(?:сколько свободно|свободное место|место) на диск[еи](?: ([a-zа-я]+))?',t)
    if m:return a('disk',drive=m[1] or 'c')
    if t in ('закрой окно','закрой активное окно','закрой текущее окно'):return a('close_window')
    if t in ('прочитай буфер','прочитай буфер обмена','что в буфере','прочитай содержимое буфера'):return a('clipboard_read')
    m=re.fullmatch(r'переведи (?:текст из )?буфер(?: обмена)?(?: на (русский|английский))?',t)
    if m:return a('clipboard_translate',target_language={'английский':'en','русский':'ru'}.get(m[1],cfg.get('clipboard_translate_target','ru')))
    if re.fullmatch(r'(?:кратко (?:перескаж[иу]|изложи)|перескаж[иу] кратко|суммируй) (?:что в |текст из )?буфер(?:е|а)?(?: обмена)?',t):return a('clipboard_summary')
    if t in ('отмени выключение','отмени выключения','отмена выключения','отключи выключение'):return a('shutdown_cancel')
    m=re.fullmatch(r'(?:выключи|выключить)(?: компьютер| ноутбук)? через (.+)',t)
    if m:return a('shutdown_prepare',seconds=duration(m[1]))
    if t in ('отмени таймер','отключи таймер','убери таймер'):return a('timer_cancel',kinds=['timer'])
    if t in ('отмени напоминания','отключи напоминания'):return a('timer_cancel',kinds=['reminder'])
    if t=='отмени все таймеры и напоминания':return a('timer_cancel',kinds=None)
    for pat in [r'каждые (.+?) напомина[йя](?: мне)? (.+)',r'напомина[йя](?: мне)? каждые (.+?(?:секунд\w*|минут\w*|час\w*)) (.+)']:
        m=re.fullmatch(pat,t)
        if m:return a('reminder',seconds=duration(m[1]),label=m[2])
    if re.match(r'^(?:поставь )?таймер\b',t):return a('timer',seconds=duration(re.sub(r'^(?:поставь )?таймер(?: на)?\s*','',t)))
    m=re.fullmatch(r'(?:запиши|сохрани) (?:идею|заметку)\s+(.+)',text.strip(),flags=re.I)
    if m:return a('note',note=m[1].strip())
    m=re.fullmatch(r'добавь (?:задачу|задание)(?: в тодоист)?\s+(.+)',text.strip(),flags=re.I)
    if m:return a('todoist_add',task_text=m[1].strip())
    m=re.fullmatch(r'(?:включи )?режим (фокуса|фокус|сна|сон|тренировки|тренировка)',t)
    if m:return a('mode',mode='focus' if m[1] in ('фокуса','фокус') else 'sleep' if m[1] in ('сна','сон') else 'workout')
    m=re.fullmatch(r'(что в гите|статус гита|последний коммит)(?: (?:проекта|в проекте|по проекту))?(?: (.+))?',t)
    if m:return a('git',project=m[2] or '',which='last' if m[1]=='последний коммит' else 'status')
    if re.match(r'^(?:добавь|запиши|внеси)\b',t) and re.search(r'грамм|килограмм|\bкг\b|творог|молок|куриц|яйц|завтрак|обед|ужин|перекус|в дневник питания|в еду',t):return a('food_log',food_text=text.strip())
    return None

# Commands without lasting side effects that the grammar recognizer may settle when the free
# transcript is a garbled version of the same phrase (see scripts/eval_asr.py).
GRAMMAR_SAFE=frozenset({'repeat','mute','screenshot','disk','clipboard_read','clipboard_translate','clipboard_summary','explain_error','confirm_in_chat','server_health','project_tests','nutrition_left','git','timer_cancel','shutdown_cancel'})
def grammar_rescue(text: str, gtext: str, alias: Mapping[str, Any] | None, min_ratio: float = .6) -> bool:
    """True when gtext names a safe command and the free transcript is close to it."""
    if not (text and gtext and alias and alias.get('action')=='quick2' and alias.get('cmd') in GRAMMAR_SAFE):return False
    return difflib.SequenceMatcher(None,norm(text),norm(gtext)).ratio()>=min_ratio
