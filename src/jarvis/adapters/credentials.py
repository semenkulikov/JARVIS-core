"""Scoped Windows Credential Manager access, via python-keyring. Never logs values.

Only Jarvis-owned credential names are addressable; restricted legacy files are fallback.
"""
from __future__ import annotations

import functools
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from jarvis.adapters import paths as PATHS

NAMES = ("webhook_auth_header", "FATSECRET_CLIENT_ID", "FATSECRET_OAUTH1_CONSUMER_SECRET", "FATSECRET_ACCESS_TOKEN", "FATSECRET_ACCESS_SECRET")
@functools.lru_cache(maxsize=1)
def backend() -> Any:
    """The Windows keyring backend, loaded once; None off Windows or without keyring."""
    if os.name != "nt": return None
    try:
        from keyring.backends.Windows import WinVaultKeyring
    except ImportError:
        # FatSecret CLI may use system Python. Reuse this app's installed pure-Python keyring.
        site = PATHS.PROJECT_ROOT / ".venv" / "Lib" / "site-packages"
        if not site.is_dir(): return None
        site_s = str(site)
        sys.path.insert(0, site_s)
        try:
            from keyring.backends.Windows import WinVaultKeyring
            return WinVaultKeyring()
        except ImportError:
            return None
        finally:
            try: sys.path.remove(site_s)
            except ValueError: pass
    return WinVaultKeyring()


def service(name: str) -> str:
    if name not in NAMES: raise ValueError("unsupported_credential_name")
    return PATHS.credential_prefix() + name


def get_secret(name: str) -> str | None:
    try:
        b = backend()
        return b.get_password(service(name), "Jarvis") if b is not None else None
    except Exception: return None


def set_secret(name: str, value: str) -> None:
    b = backend()
    if b is None: raise RuntimeError("Windows_keyring_unavailable")
    b.set_password(service(name), "Jarvis", value)


def legacy_env(path: str | Path) -> dict[str, str]:
    values = {}
    try:
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in NAMES: values[k.strip()] = v.strip()
    except OSError: pass
    return values


def webhook(cfg: Mapping[str, Any], base: str | Path) -> str:
    value = get_secret("webhook_auth_header")
    if value: return value
    value = cfg.get("webhook_auth_header", "")
    if value and "PASTE" not in value: return str(value)
    try:
        old = json.loads((Path(base) / "config.legacy.json").read_text(encoding="utf-8-sig"))
        return str(old.get("webhook_auth_header", value))
    except (OSError, ValueError, TypeError, AttributeError): return str(value)


def fatsecret_env(env: Mapping[str, str], path: str | Path) -> dict[str, str]:
    out = dict(env); old: dict[str, str] | None = None; backup: dict[str, str] | None = None
    for name in NAMES[1:]:
        value = get_secret(name) or env.get(name)
        if not value:
            if old is None: old = legacy_env(path)
            value = old.get(name)
        if not value:
            if backup is None: backup = legacy_env(str(path) + ".legacy")
            value = backup.get(name)
        if value: out[name] = value
    return out
