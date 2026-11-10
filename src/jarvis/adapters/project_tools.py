"""Project tools that touch the outside: HTTP/TCP health checks and configured test runs.

Test commands are argument lists run without a shell, in the project folder, with a timeout
and without Jarvis or FatSecret variables in the environment.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Tuple

from jarvis.core.projects import Health, Project, RunResult, Server, health_phrase, norm_name, projects, resolve, servers, summarize

log = logging.getLogger("jarvis")
_SAFE_ENV = re.compile(r"^(?:JARVIS_|FATSECRET_)")


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

    def health_reply(self, spoken: str, cfg: Mapping[str, Any]) -> str:
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
    def start_tests(self, spoken: str, cfg: Mapping[str, Any], done: Callable[[RunResult], None]) -> str:
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
        path = folder / ("tests_" + norm_name(run.project)[:40] + "_" + stamp + ".log")
        path.write_text("project: %s\nok: %s\nsummary: %s\nseconds: %.1f\n\n%s" % (
            run.project, run.ok, run.summary, run.seconds, run.output[-200_000:]), encoding="utf-8")
        return str(path)
