"""Local project commands: server health checks and configured test runs.

Hosts, URLs and test commands come only from the local config.json (nothing personal in Git).
Test commands are argument lists run without a shell, in the project folder, with a timeout
and without Jarvis or FatSecret variables in the environment. Opening pull requests is not
here: that goes to the server as a chat-confirmed request (see jarvis_codemode).
"""
from __future__ import annotations

import datetime
import difflib
import logging
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("jarvis")

DEFAULTS: Dict[str, Any] = {"servers": [], "projects": {}, "health_timeout_s": 5.0, "tests_timeout_s": 900}
PHRASES = ["статус сервера", "статус серверов", "проверь сервер", "проверь серверы", "запусти тесты проекта"]
MIN_NAME_SCORE = 0.72
_HEALTH = re.compile(r"(?:какой )?(?:статус|состояние|проверь|пингани|пингуй|пинг|жив ли|работает ли|как(?: там)?)"
                     r" (?:сервер(?:а|ов|ы|е)?|сайт(?:а|ы|ов)?|хост(?:а|ы|ов)?)(?: (?P<name>.+))?")
_TESTS = re.compile(r"(?:запусти|прогони|выполни|проверь) тесты(?: (?:проекта|в проекте|по проекту|для проекта))?(?: (?P<name>.+))?")
_SAFE_ENV = re.compile(r"^(?:JARVIS_|FATSECRET_)")


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


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zа-я]+", "", str(s).lower().replace("ё", "е"))


def resolve(spoken: str, items: Sequence[Any]) -> Optional[Any]:
    """Best item by name or spoken aliases; None when unknown or too close to call."""
    key = _norm(spoken)
    if not key:
        return None
    scored = sorted(((max(difflib.SequenceMatcher(None, key, _norm(n)).ratio() for n in (it.name,) + tuple(it.spoken)), i)
                     for i, it in enumerate(items)), reverse=True)
    if not scored or scored[0][0] < MIN_NAME_SCORE:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05 and scored[0][0] < 1:
        return None
    return items[scored[0][1]]


def servers(cfg: Dict[str, Any]) -> List[Server]:
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


def projects(cfg: Dict[str, Any]) -> List[Project]:
    out: List[Project] = []
    for name, raw in (cfg.get("projects") or {}).items():
        if not isinstance(raw, dict):
            continue
        cmd = raw.get("test_command")
        if not raw.get("path") or not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
            continue
        out.append(Project(str(name), os.path.expandvars(str(raw["path"])), tuple(cmd),
                           tuple(str(x) for x in raw.get("spoken") or ()),
                           float(raw.get("timeout_s") or cfg.get("tests_timeout_s", 900))))
    return out


def check_http(url: str, timeout: float, opener: Callable[..., Any] = urllib.request.urlopen) -> Tuple[bool, str]:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "JarvisHealth/1"})
    try:
        with opener(req, timeout=timeout) as r:
            code = int(getattr(r, "status", 200))
            return code < 400, "код " + str(code)
    except urllib.error.HTTPError as e:
        return False, "код " + str(e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return False, "таймаут" if isinstance(reason, socket.timeout) or "timed out" in str(reason) else "нет соединения"


def check_tcp(host: str, port: int, timeout: float,
              connect: Callable[..., Any] = socket.create_connection) -> Tuple[bool, str]:
    try:
        connect((host, port), timeout=timeout).close()
        return True, ""
    except socket.timeout:
        return False, "таймаут"
    except OSError:
        return False, "нет соединения"


class ProjectTools:
    def __init__(self, home: Path, opener: Callable[..., Any] = urllib.request.urlopen,
                 connect: Callable[..., Any] = socket.create_connection,
                 runner: Callable[..., Any] = subprocess.run, clock: Callable[[], float] = time.monotonic):
        self.home = Path(home); self.opener = opener; self.connect = connect; self.runner = runner; self.clock = clock
        self._running: Dict[str, threading.Thread] = {}; self._lock = threading.Lock()

    # ---------- health ----------
    def check(self, server: Server, timeout: float) -> Health:
        t0 = self.clock()
        if server.url:
            ok, detail = check_http(server.url, timeout, self.opener)
        else:
            ok, detail = check_tcp(server.host, server.port, timeout, self.connect)
        h = Health(server.name, ok, detail, int((self.clock() - t0) * 1000))
        log.info("health %s ok=%s detail=%s ms=%d", h.name, h.ok, h.detail, h.ms)
        return h

    def health_reply(self, spoken: str, cfg: Dict[str, Any]) -> str:
        items = servers(cfg)
        if not items:
            return "Серверы не настроены, сэр. Добавьте их в настройки."
        chosen = [resolve(spoken, items)] if spoken else items
        if chosen == [None]:
            return "Не знаю такой сервер, сэр."
        timeout = float(cfg.get("health_timeout_s", 5))
        results = [self.check(s, timeout) for s in chosen]  # type: ignore[arg-type]
        return health_phrase(results)

    # ---------- tests ----------
    def start_tests(self, spoken: str, cfg: Dict[str, Any], done: Callable[[RunResult], None]) -> str:
        items = projects(cfg)
        if not items:
            return "Команды тестов не настроены, сэр."
        p = resolve(spoken, items) if spoken else (items[0] if len(items) == 1 else None)
        if p is None:
            return "Назовите проект с настроенными тестами, сэр." if not spoken else "Не знаю тестов такого проекта, сэр."
        if not Path(p.path).is_dir():
            return "Папка проекта " + p.name + " не найдена, сэр."
        with self._lock:
            if p.name in self._running and self._running[p.name].is_alive():
                return "Тесты проекта " + p.name + " уже идут, сэр."
            th = threading.Thread(target=lambda: done(self.run_tests(p)), name="tests-" + p.name, daemon=True)
            self._running[p.name] = th
        th.start()
        return "Запускаю тесты проекта " + p.name + ", сэр. Скажу, когда закончатся."

    def run_tests(self, p: Project) -> RunResult:
        t0 = self.clock(); env = {k: v for k, v in os.environ.items() if not _SAFE_ENV.match(k)}
        kw: Dict[str, Any] = {"cwd": p.path, "env": env, "capture_output": True, "text": True,
                              "encoding": "utf-8", "errors": "replace", "timeout": p.timeout_s}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000
        try:
            r = self.runner(list(p.test_command), **kw)
            output = (r.stdout or "") + (r.stderr or "")
            ok, summary = summarize(output, int(r.returncode))
        except subprocess.TimeoutExpired:
            output, ok, summary = "", False, "не уложились в " + str(int(p.timeout_s)) + " секунд"
        except OSError as e:
            output, ok, summary = "", False, "команда не запустилась (" + type(e).__name__ + ")"
        run = RunResult(p.name, ok, summary, round(self.clock() - t0, 1), output)
        run.report = self.write_report(run)
        log.info("tests %s ok=%s summary=%r seconds=%.1f report=%s", p.name, ok, summary, run.seconds, run.report)
        return run

    def write_report(self, run: RunResult) -> str:
        folder = self.home / "reports"; folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = folder / ("tests_" + _norm(run.project)[:40] + "_" + stamp + ".log")
        path.write_text("project: %s\nok: %s\nsummary: %s\nseconds: %.1f\n\n%s" % (
            run.project, run.ok, run.summary, run.seconds, run.output[-200_000:]), encoding="utf-8")
        return str(path)


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
