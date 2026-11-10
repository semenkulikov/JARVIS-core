"""Configuration: load ``config.json`` over defaults, reload on change, migrate and validate.

Values stay a plain dict so the older modules and user files keep working; typed views such as
:class:`jarvis.core.followup.FollowupSettings` read from it.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from jarvis.core import migrations as MIGRATIONS

Config = dict[str, Any]
log = logging.getLogger("jarvis")


@dataclass(frozen=True)
class ConfigIssue:
    key: str
    expected: str
    got: str

    def __str__(self) -> str:
        return f"{self.key}: expected {self.expected}, got {self.got}"


def _kind(v: Any) -> str:
    if isinstance(v, bool): return "bool"
    if isinstance(v, (int, float)): return "number"
    if isinstance(v, (str, list, tuple)): return "text or list"
    if isinstance(v, dict): return "object"
    return "null" if v is None else type(v).__name__


def validate(cfg: Mapping[str, Any], defaults: Mapping[str, Any]) -> list[ConfigIssue]:
    """Values whose type differs from the default's (numbers interchangeable, phrase text or list)."""
    issues = []
    for key, default in defaults.items():
        if default is None or key not in cfg: continue
        want, got = _kind(default), _kind(cfg[key])
        if want != got: issues.append(ConfigIssue(key, want, got))
    return issues


def merge_aliases(user: Iterable[Any] | None, defaults: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """User aliases override by name but keep the default phrases (unless "replace": true); new defaults are added."""
    if not user: return [dict(a) for a in defaults]
    defaults = list(defaults)
    out = []; by_name = {a.get("name"): a for a in defaults}
    for a in user:
        if not isinstance(a, dict) or str(a.get("name", "")).startswith("chat_"): continue
        d = by_name.get(a.get("name"))
        if d is not None and not a.get("replace"):
            a = dict(a, phrases=list(dict.fromkeys(list(a.get("phrases") or []) + list(d.get("phrases") or []))))
        out.append(a)
    names = {a.get("name") for a in out}
    return out + [dict(a) for a in defaults if a.get("name") not in names]


class ConfigStore:
    """Current configuration; the file is read again only when its modification time changes."""

    def __init__(self, path: str, defaults: Mapping[str, Any], finalize: Callable[[Config], None] = lambda cfg: None,
                 migrate: Callable[[Config, Mapping[str, Any]], list[int]] = MIGRATIONS.migrate) -> None:
        self.path, self.defaults, self.finalize, self.migrate = path, defaults, finalize, migrate
        self._mtime: float | None = None
        self._cfg: Config | None = None
        self._lock = threading.Lock()

    def load(self) -> Config:
        with self._lock:
            return self._load()

    def _load(self) -> Config:
        try: m: float | None = os.path.getmtime(self.path)
        except Exception: m = None
        if self._cfg is not None and self._mtime == m: return self._cfg
        cfg = dict(self.defaults)
        try:
            with open(self.path, encoding="utf-8-sig") as f: cfg.update(json.load(f))
            if self._mtime is not None: log.info("config reloaded")
        except Exception as e:
            log.warning("config load failed: %s", e)
            if self._cfg is not None: return self._cfg
        applied = self.migrate(cfg, self.defaults)
        if applied: log.info("config migrations applied in memory: %s", applied)
        self.finalize(cfg)
        for issue in validate(cfg, self.defaults): log.warning("config value %s", issue)
        self._mtime, self._cfg = m, cfg
        return cfg
