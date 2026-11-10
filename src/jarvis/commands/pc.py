"""Laptop actions: media keys, screen, timers, battery, projects, programs and shell aliases."""
from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import sys
import time

from jarvis.core import quick as QUICK
from jarvis.core import text as JT
from jarvis.commands.base import Alias, CommandContext
from jarvis.commands.registry import handles
from jarvis.core.matching import norm_phrase

log = logging.getLogger("jarvis")
CREATE_NO_WINDOW = 0x08000000
VK = {"vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD, "next": 0xB0, "prev": 0xB1, "play": 0xB3}  # Windows media keys


def _startfile(target: str) -> None:
    if sys.platform != "win32": raise OSError("os.startfile is Windows-only")
    os.startfile(target)


@handles("key")
def key(ctx: CommandContext, al: Alias) -> None:
    vk = VK[al["key"]]; n = int(al.get("times", 1))
    if ctx.test: log.info("TEST: would send vk=0x%X x%d", vk, n)
    else: ctx.services.laptop().press(vk, n)
    if not al.get("silent") and al["key"] != "mute": ctx.ack(al)


@handles("monitor_off")
def monitor_off(ctx: CommandContext, al: Alias) -> None:
    ctx.ack(al)
    if ctx.test: log.info("TEST: would turn monitor off")
    else: time.sleep(0.5); ctx.services.laptop().monitor_off()


@handles("timer")
def timer(ctx: CommandContext, al: Alias) -> None:
    say, cfg = ctx.services.say, ctx.cfg
    secs = QUICK.duration(re.sub(r"^.*?таймер\w*(?: на)?\s*", "", QUICK.norm(ctx.text)))
    if not secs: say("На сколько поставить таймер, сэр?", cfg); return
    ctx.services.controller().timers.add(secs, ctx.text)
    say(f"Таймер на {QUICK.duration_label(secs)}, сэр.", cfg)


@handles("timer_cancel")
def timer_cancel(ctx: CommandContext, al: Alias) -> None:
    n = ctx.services.controller().timers.cancel()
    ctx.services.say("Таймер отменён, сэр." if n else "Активных таймеров нет, сэр.", ctx.cfg)


@handles("battery")
def battery(ctx: CommandContext, al: Alias) -> None:
    pct, ac = ctx.services.laptop().battery()
    if pct is None: ctx.services.say("Не вижу батарею, сэр.", ctx.cfg); return
    ctx.services.say(f"Заряд {JT.num_ru(pct)} {JT.plural(pct, 'процент', 'процента', 'процентов')}, "
                     + ("зарядка подключена, сэр." if ac else "работаем от батареи, сэр."), ctx.cfg)


@handles("temperature")
def temperature(ctx: CommandContext, al: Alias) -> None:
    t = ctx.services.laptop().temperature_c()
    if t is None: ctx.services.say("Датчик температуры сейчас недоступен, сэр.", ctx.cfg)
    else: ctx.services.say(f"Температура системы {JT.num_ru(t)} {JT.plural(t, 'градус', 'градуса', 'градусов')}, сэр.", ctx.cfg)


@handles("open_project")
def open_project(ctx: CommandContext, al: Alias) -> None:
    say, cfg = ctx.services.say, ctx.cfg
    rest = " ".join(norm_phrase(ctx.text)); rest = re.sub(r"^.*?проект\w*\s*", "", rest)
    lp = ctx.services.laptop()
    path, score = lp.find_project(rest, lambda w: JT.latin(w, ctx.cfg.get("latin_words")), ctx.cfg.get("projects_dir") or None)
    log.info("project match %r -> %s (%.2f)", rest, path, score)
    exe = lp.cursor_exe()
    if not path or score < 0.5: say("Не нашёл такой проект, сэр.", cfg); return
    if not exe: say("Не нашёл Курсор, сэр.", cfg); return
    if ctx.test: log.info("TEST: would run %s %s", exe, path)
    else: subprocess.Popen([exe, path], creationflags=CREATE_NO_WINDOW)
    ctx.ack(al)


@handles("open_github")
def open_github(ctx: CommandContext, al: Alias) -> None:
    url = ctx.services.status.github_url()
    if not url:
        lp = ctx.services.laptop()
        r = lp.recent_repo(ctx.cfg.get("projects_dir") or None); url = lp.remote_url(r) if r else None; log.info("recent repo %s -> %s", r, url)
    if not url: ctx.services.say("Не нашёл репозиторий, сэр.", ctx.cfg); return
    if ctx.test: log.info("TEST: would open %s", url)
    else: _startfile(url)
    ctx.ack(al)


@handles("open")
def open_target(ctx: CommandContext, al: Alias) -> None:
    tgt = os.path.expandvars(al.get("target", ""))
    if ctx.test: log.info("TEST: would open %s (exists=%s)", tgt, os.path.exists(tgt) or tgt.startswith("http")); ctx.ack(al); return
    try:
        if not re.match(r"^\w+:", tgt) or re.match(r"^[A-Za-z]:\\", tgt):
            if not os.path.exists(tgt): raise FileNotFoundError(tgt)
        _startfile(tgt); ctx.ack(al)
    except Exception as e:
        log.warning("open failed %s: %s", tgt, e); ctx.services.say("Не нашёл приложение, сэр.", ctx.cfg)


@handles("lock")
def lock(ctx: CommandContext, al: Alias) -> None:
    ctx.ack(al)
    if ctx.test: log.info("TEST: would lock"); return
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])


@handles("shell")
def shell(ctx: CommandContext, al: Alias) -> None:
    ctx.ack(al)
    target = str(al.get("target", "")).strip()
    if ctx.test: log.info("TEST: would run %s", target); return
    if not target: return
    subprocess.Popen(shlex.split(target, posix=False), shell=False)
