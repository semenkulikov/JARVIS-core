"""User-level, hidden, stdlib-only listener supervisor. Started by the VBS launcher or at logon.

An intentional stop exits the supervisor too; only an explicit launcher start resumes it.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

from jarvis.adapters import paths as PATHS
from jarvis.adapters import runtime as R

log = logging.getLogger("jarvis.supervisor")
CREATE_NO_WINDOW = 0x08000000
STABLE_S = 300  # a worker that ran this long resets the crash back-off


def spawn_worker() -> subprocess.Popen[bytes]:
    exe = Path(sys.executable)
    if os.name == "nt" and exe.with_name("pythonw.exe").is_file(): exe = exe.with_name("pythonw.exe")
    return subprocess.Popen([str(exe), str(PATHS.SOURCE_DIR / "jarvis_voice.py")], cwd=str(PATHS.HOME),
                            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)


def run(base: str | Path | None = None, spawn: Callable[[], Any] | None = None, sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic, alive: Callable[[], bool] | None = None, limit: int | None = None) -> str:
    """Keep one listener running until an intentional stop; ``limit`` bounds the loop in tests."""
    home = Path(base if base is not None else PATHS.HOME); spawn = spawn or spawn_worker
    alive = alive or (lambda: R.exists(home, "listener"))
    child: Any = None; failures = 0; started = clock(); retry_at = 0.0; steps = 0
    while limit is None or steps < limit:
        steps += 1
        if (home / "stop").exists(): R.mark_stop(home)
        intentional = R.stop_marker(home).exists()
        if child is not None:
            code = child.poll()
            if code is not None:
                log.info("worker exited code=%s intentional=%s", code, intentional); child = None
                if intentional: return "intentional_stop"
                failures = 1 if clock() - started >= STABLE_S else failures + 1; retry_at = clock() + R.crash_delay(failures)
                log.warning("crash recovery delay_s=%d failures=%d", R.crash_delay(failures), failures)
        if intentional:
            if child is None and not alive():
                # The listener may already have consumed stop. Retain marker, never auto-resume.
                try: (home / "stop").unlink()
                except FileNotFoundError: pass
                return "intentional_stop"
        elif child is None and clock() >= retry_at and not alive():
            try:
                child = spawn(); started = clock(); log.info("listener launched pid=%s", getattr(child, "pid", "fixture"))
            except Exception as e:
                failures += 1; retry_at = clock() + R.crash_delay(failures)
                log.warning("launch failed type=%s delay_s=%d", type(e).__name__, R.crash_delay(failures))
        sleep(.5)
    return "test_limit"


def main() -> None:
    folder = PATHS.log_dir(); folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "supervisor.log", maxBytes=500000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s")); log.addHandler(handler); log.setLevel(logging.INFO)
    home = PATHS.HOME
    guard = R.Singleton(home, "supervisor")
    acquired = guard.acquire()
    # An explicit start just after listener exit may overlap the old supervisor's final poll.
    if not acquired and R.stop_marker(home).exists():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not acquired: time.sleep(.25); acquired = guard.acquire()
    if not acquired: log.info("supervisor already running; duplicate start ignored"); return
    try:
        R.clear_stop(home); log.info("supervisor start pid=%s", os.getpid()); reason = run(home); log.info("supervisor exit reason=%s", reason)
    finally: guard.close()


def entry() -> None:
    """Process entry: a fatal error is logged by type only, never with a traceback that could hold paths or secrets."""
    try: main()
    except Exception as e: log.error("supervisor fatal type=%s", type(e).__name__)
