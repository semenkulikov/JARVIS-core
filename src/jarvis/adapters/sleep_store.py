"""Persistent sleep end time, so a restart does not wake Jarvis early."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("jarvis")


class SleepState:
    """Persistent ``until`` timestamp; ``poll`` reports the moment sleep ends."""

    def __init__(self, path: os.PathLike[str] | str, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self.until: Optional[float] = None
        try:
            if self.path.exists():
                value = json.loads(self.path.read_text(encoding="utf-8-sig")).get("until")
                self.until = float(value) if value else None
        except Exception as e:  # corrupt state must never keep Jarvis asleep
            log.warning("sleep state unreadable (%s); awake", type(e).__name__)

    def active(self) -> bool:
        return self.until is not None and self.clock() < self.until

    def remaining(self) -> float:
        return max(0.0, (self.until or 0.0) - self.clock())

    def start(self, secs: float) -> None:
        self.until = self.clock() + float(secs)
        self._save()
        log.info("SLEEP on for %.0fs (until %s)", secs, time.strftime("%H:%M:%S", time.localtime(self.until)))

    def stop(self, reason: str) -> bool:
        if self.until is None:
            return False
        self.until = None
        self._save()
        log.info("SLEEP off (%s)", reason)
        return True

    def poll(self, wake_file: Optional[os.PathLike[str] | str] = None) -> Optional[str]:
        """Return the wake reason once ('timeout' / 'wake_file'), else None."""
        if self.until is None:
            return None
        if wake_file is not None and os.path.exists(wake_file):
            try:
                os.remove(wake_file)
            except OSError:
                pass
            self.stop("wake_file")
            return "wake_file"
        if self.clock() >= self.until:
            self.stop("timeout")
            return "timeout"
        return None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "until": self.until}), encoding="utf-8")
        os.replace(tmp, self.path)
