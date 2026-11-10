"""Local project commands, pure part: phrases, config parsing, name matching and spoken results.

Hosts, URLs and test commands come only from the local config.json (nothing personal in Git).
Test commands are argument lists run without a shell, in the project folder, with a timeout
and without Jarvis or FatSecret variables in the environment. Opening pull requests is not
here: that goes to the server as a chat-confirmed request (see jarvis.core.codemode).
The network checks and test runs live in jarvis.adapters.project_tools.
"""
from __future__ import annotations

import difflib
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from jarvis.core.fold import fold

log = logging.getLogger("jarvis")

DEFAULTS: Dict[str, Any] = {"servers": [], "projects": {}, "health_timeout_s": 5.0, "tests_timeout_s": 900}
PHRASES = ["статус сервера", "статус серверов", "проверь сервер", "проверь серверы", "запусти тесты проекта"]
MIN_NAME_SCORE = 0.72
_HEALTH = re.compile(r"(?:какой )?(?:статус|состояние|проверь|пингани|пингуй|пинг|жив ли|работает ли|как(?: там)?)"
                     r" (?:сервер(?:а|ов|ы|е)?|сайт(?:а|ы|ов)?|хост(?:а|ы|ов)?)(?: (?P<name>.+))?")
_TESTS = re.compile(r"(?:запусти|прогони|выполни|проверь) тесты(?: (?:проекта|в проекте|по проекту|для проекта))?(?: (?P<name>.+))?")


@dataclass(frozen=True)
class Server:
    name: str
    url: str = ""
    host: str = ""
    port: int = 443
    spoken: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Project:
    name: str
    path: str
    test_command: Tuple[str, ...]
    spoken: Tuple[str, ...] = ()
    timeout_s: float = 900.0


@dataclass
class Health:
    name: str
    ok: bool
    detail: str = ""
    ms: int = 0


@dataclass
class RunResult:
    project: str
    ok: bool
    summary: str
    seconds: float
    output: str = ""
    report: str = ""


def _alias(cmd: str, **kw: Any) -> Dict[str, Any]:
    return {"name": "quick_" + cmd, "action": "quick2", "cmd": cmd, **kw}


def match(t: str) -> Optional[Dict[str, Any]]:
    """t is normalized (lower case, ё -> е)."""
    m = _HEALTH.fullmatch(t)
    if m:
        return _alias("server_health", target=(m.group("name") or "").strip())
    m = _TESTS.fullmatch(t)
    if m:
        return _alias("project_tests", project=(m.group("name") or "").strip())
    return None


def norm_name(s: str) -> str:
    return re.sub(r"[^0-9a-zа-я]+", "", fold(str(s)))


def resolve(spoken: str, items: Sequence[Any]) -> Optional[Any]:
    """Best item by name or spoken aliases; None when unknown or too close to call."""
    key = norm_name(spoken)
    if not key:
        return None
    scored = sorted(((max(difflib.SequenceMatcher(None, key, norm_name(n)).ratio() for n in (it.name,) + tuple(it.spoken)), i)
                     for i, it in enumerate(items)), reverse=True)
    if not scored or scored[0][0] < MIN_NAME_SCORE:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05 and scored[0][0] < 1:
        return None
    return items[scored[0][1]]


def servers(cfg: Mapping[str, Any]) -> List[Server]:
    out: List[Server] = []
    for raw in cfg.get("servers") or []:
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        url = str(raw.get("url") or "")
        if url and urllib.parse.urlparse(url).scheme not in ("http", "https"):
            log.warning("server %s skipped: url must be http(s)", raw["name"]); continue
        if not url and not raw.get("host"):
            continue
        out.append(Server(str(raw["name"]), url, str(raw.get("host") or ""), int(raw.get("port") or 443),
                          tuple(str(x) for x in raw.get("spoken") or ())))
    return out


def projects(cfg: Mapping[str, Any]) -> List[Project]:
    out: List[Project] = []
    for name, raw in (cfg.get("projects") or {}).items():
        if not isinstance(raw, dict):
            continue
        cmd = raw.get("test_command")
        if not raw.get("path") or not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
            continue
        out.append(Project(str(name), os.path.expandvars(str(raw["path"])), tuple(cmd),
                           tuple(str(x) for x in raw.get("spoken") or ()),
                           float(raw.get("timeout_s") or cfg.get("tests_timeout_s") or 900)))
    return out


_COUNTS = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)")


def summarize(output: str, returncode: int) -> Tuple[bool, str]:
    """pytest-style counts when present, otherwise the exit code."""
    tail = "\n".join(output.strip().splitlines()[-5:])
    counts: Dict[str, int] = {}
    for n, kind in _COUNTS.findall(tail):
        counts[kind.rstrip("s") if kind.startswith("error") else kind] = int(n)
    ok = returncode == 0
    if counts:
        parts = []
        if counts.get("passed"): parts.append(str(counts["passed"]) + " успешно")
        if counts.get("failed"): parts.append(str(counts["failed"]) + " с ошибкой")
        if counts.get("error"): parts.append(str(counts["error"]) + " сбоев")
        if counts.get("skipped"): parts.append(str(counts["skipped"]) + " пропущено")
        return ok, ", ".join(parts) or "код " + str(returncode)
    return ok, "код выхода " + str(returncode)


def tests_phrase(run: RunResult) -> str:
    head = "Тесты проекта " + run.project + (" прошли" if run.ok else " не прошли")
    return head + ": " + run.summary + ", сэр." + ("" if run.ok else " Подробности в отчёте.")


def health_phrase(results: List[Health]) -> str:
    if len(results) == 1:
        h = results[0]
        if h.ok:
            return "Сервер " + h.name + " отвечает за " + str(h.ms) + " миллисекунд, сэр."
        return "Сервер " + h.name + " не отвечает: " + (h.detail or "нет соединения") + ", сэр."
    down = [h for h in results if not h.ok]
    if not down:
        return "Все серверы отвечают, сэр: " + str(len(results)) + "."
    return "Не отвечают: " + ", ".join(h.name + " (" + (h.detail or "нет соединения") + ")" for h in down) + \
        ". Остальные в порядке, сэр."
