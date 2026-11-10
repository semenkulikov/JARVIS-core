"""Laptop helpers: media keys, screen off, battery, temperature, project folders and the Cursor executable.

The module itself implements jarvis.core.ports.Laptop; tests patch its functions.
"""
from __future__ import annotations

import ctypes
import difflib
import logging
import os
import re
import subprocess
import time
from typing import Any, Callable

from jarvis.adapters.paths import PROJECTS_DIR

log = logging.getLogger("jarvis")
CREATE_NO_WINDOW = 0x08000000
# Windows-only ctypes entry points (absent from the Linux stubs mypy also checks against).
_WIN: Any = ctypes


def press(vk: int, times: int = 1) -> None:
    u = _WIN.windll.user32
    for _ in range(times):
        u.keybd_event(vk, 0, 0, 0); u.keybd_event(vk, 0, 2, 0); time.sleep(0.02)
    log.info("keys sent: vk=0x%X x%d", vk, times)


def monitor_off() -> None:
    from ctypes import wintypes
    u = _WIN.windll.user32
    u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                      ctypes.c_void_p]
    r = u.SendMessageTimeoutW(0xFFFF, 0x0112, 0xF170, 2, 0x0002, 1000, None)
    log.info("monitor off sent (%s)", r)


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte), ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_byte), ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def battery() -> tuple[int | None, bool]:
    s = _PowerStatus(); _WIN.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
    pct = int(s.BatteryLifePercent) & 0xFF
    return (None if pct == 255 else pct), s.ACLineStatus == 1


def temperature_c() -> int | None:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation | "
                              "Measure-Object -Property HighPrecisionTemperature -Maximum).Maximum"],
                             capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW).stdout.strip()
        v = float(out.replace(",", "."))
        return round(v / 10 - 273.15)
    except Exception as e:
        log.warning("temperature read failed: %s", e); return None


def projects_root(projects_dir: str | None = None) -> str:
    """The configured projects folder (config ``projects_dir``), else JARVIS_PROJECTS / ~/Projects."""
    return os.path.expanduser(os.path.expandvars(projects_dir)) if projects_dir else str(PROJECTS_DIR)


def _spoken(name: str, latin_fn: Callable[[str], str]) -> str:
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+|[А-Яа-яЁё]+", name)
    return " ".join(latin_fn(p).lower() for p in parts)


def _folders(root: str) -> list[str]:
    return os.listdir(root) if os.path.isdir(root) else []


def find_project(spoken: str, latin_fn: Callable[[str], str], projects_dir: str | None = None) -> tuple[str | None, float]:
    """Folder whose (transliterated) name sounds closest to ``spoken`` and its similarity."""
    root = projects_root(projects_dir)
    spoken = re.sub(r"\s+", "", spoken.lower().replace("ё", "е"))
    if not spoken: return None, 0
    best, bs = None, 0.0
    for d in _folders(root):
        p = os.path.join(root, d)
        if not os.path.isdir(p): continue
        cands = [re.sub(r"\s+", "", _spoken(d, latin_fn)), d.lower()]
        s = max(difflib.SequenceMatcher(None, spoken, c).ratio() for c in cands)
        if s > bs: best, bs = p, s
    return best, bs


def recent_repo(projects_dir: str | None = None) -> str | None:
    root = projects_root(projects_dir)
    best, bt = None, 0.0
    for d in _folders(root):
        g = os.path.join(root, d, ".git")
        if not os.path.isdir(g): continue
        marks = [os.path.join(g, f) for f in ("index", "HEAD", "FETCH_HEAD", "ORIG_HEAD", "logs")]
        t = max([os.path.getmtime(x) for x in marks if os.path.exists(x)] or [0.0])
        if t > bt: best, bt = os.path.join(root, d), t
    return best


def remote_url(repo: str) -> str | None:
    try:
        u = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10,
                           creationflags=CREATE_NO_WINDOW).stdout.strip()
    except Exception as e:
        log.warning("git remote failed: %s", e); return None
    if not u: return None
    m = re.match(r"git@([^:]+):(.+?)(\.git)?$", u)
    if m: return f"https://{m.group(1)}/{m.group(2)}"
    return re.sub(r"\.git$", "", re.sub(r"https://[^@/]+@", "https://", u))


def cursor_exe() -> str | None:
    for p in [os.path.expandvars(r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe"), r"C:\Program Files\Cursor\Cursor.exe"]:
        if os.path.exists(p): return p
    return None
