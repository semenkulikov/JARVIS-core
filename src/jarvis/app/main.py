"""Process entry: logging, the single-instance guard, the composition root and the exit code."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

import jarvis_paths as PATHS
import jarvis_runtime as RUNTIME

LOG_FILE = "jarvis_voice.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def configure_logging(log_dir: str) -> logging.Logger:
    """The «jarvis» logger: rotating jarvis_voice.log, 2 MB x 3, one plain line per event."""
    os.makedirs(log_dir, exist_ok=True)
    log = logging.getLogger("jarvis")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = RotatingFileHandler(os.path.join(log_dir, LOG_FILE), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter(LOG_FORMAT))
        log.addHandler(h)
    return log


def run() -> int:
    home = str(PATHS.HOME)
    log = configure_logging(str(PATHS.log_dir()))
    # Imported after logging is set up so import-time warnings of the legacy modules reach the log.
    from jarvis.app.context import build_app
    guard = RUNTIME.Singleton(home, "listener")
    if not guard.acquire():
        log.info("listener already running; duplicate start ignored"); return 0
    try:
        app = build_app(home)
        app.listener.run()
    except Exception as e:
        log.exception("fatal: %s", e); raise
    finally: guard.close()
    return int(app.c.state.exit_code or 0)
