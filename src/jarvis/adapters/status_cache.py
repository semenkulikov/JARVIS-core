"""Reads the status snapshot (``cache/status.json``) the user's server keeps up to date."""
from __future__ import annotations

import json
import logging
from typing import Any

from jarvis.core import status as STATUS

Config = dict[str, Any]
log = logging.getLogger("jarvis")


class StatusCache:
    """Implements :class:`jarvis.core.ports.StatusSource`; every read goes to the file, it is small."""

    def __init__(self, path: str) -> None:
        self.path = path

    def read(self) -> Any:
        with open(self.path, encoding="utf-8-sig") as f: return json.load(f)

    def load(self) -> dict[str, Any] | None:
        try: data = self.read()
        except Exception: return None
        return data if isinstance(data, dict) else None

    def cached_status(self, field: str | None, cfg: Config) -> tuple[str, str, float | None]:
        try:
            return STATUS.status_answer(self.read(), field, cfg)
        except Exception as e:
            log.info("status snapshot unusable: %s", type(e).__name__); return "missing", "", None

    def tasks_snapshot(self, cfg: Config) -> tuple[Any, bool, str]:
        """(snapshot or None, whether it is fresh, «Данные на …» stamp) for the task answers."""
        cache, fresh, stamp = None, False, ""
        try:
            cache = self.read()
            decision, _ = STATUS.cache_age_policy(cache["updated"], cfg); fresh = decision == "fresh"
            stamp = "Данные на " + STATUS.spoken_time(cache["updated"]) + "."
        except Exception as e:
            log.info("tasks: snapshot unusable (%s)", type(e).__name__)
        return cache, fresh, stamp

    def github_url(self) -> str | None:
        """The first project link in the snapshot as a GitHub URL."""
        url = None
        try:
            pj = self.read().get("projects")
            for p in (pj if isinstance(pj, list) else [pj] if pj else []):
                u = p if isinstance(p, str) else (p.get("github") or p.get("url") or p.get("repo") or "")
                if u: url = u if u.startswith("http") else "https://github.com/" + u.strip("/"); break
        except Exception as e: log.info("projects field unavailable: %s", e)
        return url
