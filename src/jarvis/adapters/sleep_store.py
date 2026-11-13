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
        self.quiet_end = False  # sleep until the alarm: the alarm speaks, no «Я снова на связи»
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8-sig"))
                value = data.get("until")
                self.until = float(value) if value else None
                self.quiet_end = bool(data.get("quiet_end", False))
        except Exception as e:  # corrupt state must never keep Jarvis asleep
            log.warning("sleep state unreadable (%s); awake", type(e).__name__)

    def active(self) -> bool:
        return self.until is not None and self.clock() < self.until

    def remaining(self) -> float:
        return max(0.0, (self.until or 0.0) - self.clock())

    def start(self, secs: float, quiet_end: bool = False) -> None:
        self.until = self.clock() + float(secs); self.quiet_end = quiet_end
        self._save()
        log.info("SLEEP on for %.0fs (until %s)", secs, time.strftime("%H:%M:%S", time.localtime(self.until)))

    def stop(self, reason: str) -> bool:
        if self.until is None:
            return False
        self.until = None; self.quiet_end = False
        self._save()
        log.info("SLEEP off (%s)", reason)
        return True

    def poll(self, wake_file: Optional[os.PathLike[str] | str] = None) -> Optional[str]:
        """Return the wake reason once ('timeout' / 'timeout_quiet' / 'wake_file'), else None."""
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
            reason = "timeout_quiet" if self.quiet_end else "timeout"
            self.stop(reason)
            return reason
        return None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "until": self.until, "quiet_end": self.quiet_end}), encoding="utf-8")
        os.replace(tmp, self.path)
