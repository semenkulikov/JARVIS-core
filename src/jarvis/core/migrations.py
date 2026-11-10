"""Versioned configuration migrations, applied in memory on every config load.

A config without ``config_version`` comes from an installation older than the public
repository; its listener forced these values at load time, so they are kept as code.
New configs (``config.example.json``) already carry the current version.
"""
from typing import Any, Callable, Dict, List, Mapping, Tuple

Config = Dict[str, Any]


def _v1_listener_tuning(cfg: Config, defaults: Mapping[str, Any]) -> None:
    cfg["phrase_silence_s"] = 0.95   # tolerate natural pauses (acoustic guard does the rest)
    cfg["bargein_min_conf"] = 0.60   # barge-in also needs free-recognizer corroboration
    cfg["ack_stop"] = list(defaults["ack_stop"])


MIGRATIONS: List[Tuple[int, Callable[[Config, Mapping[str, Any]], None]]] = [
    (1, _v1_listener_tuning),
]
CURRENT = MIGRATIONS[-1][0]


def migrate(cfg: Config, defaults: Mapping[str, Any]) -> List[int]:
    """Bring ``cfg`` to CURRENT in place; returns the versions that were applied."""
    try:
        version = int(cfg.get("config_version") or 0)
    except (TypeError, ValueError):
        version = 0
    applied = []
    for target, step in MIGRATIONS:
        if version < target:
            step(cfg, defaults)
            applied.append(target)
    cfg["config_version"] = max(version, CURRENT)
    return applied
