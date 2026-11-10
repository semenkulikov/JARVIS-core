"""Small Windows singleton and intentional-stop primitives; no side effects on import."""
from __future__ import annotations

import ctypes
import hashlib
import time
from pathlib import Path
from typing import Any

Base = str | Path
MEMORY_RESTART_CODE = 75  # non-zero, not intentional: the supervisor relaunches after 2 s
_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x100000
# WinDLL and the last-error helpers exist only on Windows (tests fake them elsewhere).
_WIN: Any = ctypes


def stop_marker(base: Base) -> Path: return Path(base) / "cache" / "intentional_stop"


def mark_stop(base: Base) -> None:
    p = stop_marker(base); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(str(time.time()), encoding="ascii")


def clear_stop(base: Base) -> None:
    for p in (stop_marker(base), Path(base) / "stop"):
        try: p.unlink()
        except FileNotFoundError: pass


def mutex_name(base: Base, role: str) -> str:
    digest = hashlib.sha256(str(Path(base).resolve()).lower().encode()).hexdigest()[:16]
    return "Local\\JarvisVoiceAssistant_" + digest + "_" + role


def _kernel32() -> Any:
    k = _WIN.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]; k.CreateMutexW.restype = ctypes.c_void_p
    k.OpenMutexW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]; k.OpenMutexW.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


class Singleton:
    """A named Windows mutex held for the process lifetime; ``acquire`` is False when another owner has it."""

    def __init__(self, base: Base, role: str) -> None:
        self.name = mutex_name(base, role); self.handle: int | None = None; self.api: Any = None

    def acquire(self) -> bool:
        k = _kernel32()
        _WIN.set_last_error(0); h = k.CreateMutexW(None, 0, self.name); error = _WIN.get_last_error()
        if not h: raise OSError("singleton_mutex_failed")
        if error == _ALREADY_EXISTS: k.CloseHandle(h); return False
        self.handle = h; self.api = k; return True

    def close(self) -> None:
        if self.handle: self.api.CloseHandle(self.handle); self.handle = None


def exists(base: Base, role: str) -> bool:
    k = _kernel32()
    h = k.OpenMutexW(_SYNCHRONIZE, 0, mutex_name(base, role))
    if h: k.CloseHandle(h); return True
    return False


def crash_delay(failures: int, minimum: float = 2, maximum: float = 300) -> float:
    return min(maximum, minimum * 2 ** max(0, min(16, failures - 1)))


def memory_over_limit(priv_mb: float, limit_mb: Any) -> bool:
    """True when private commit exceeds a positive limit (0/None disables the guard)."""
    try: limit = float(limit_mb or 0)
    except (TypeError, ValueError): return False
    return limit > 0 and float(priv_mb) > limit


def idle_for(last_activity: float | None, now: float) -> float:
    """Seconds since the last activity timestamp (monotonic); 0 activity means since boot."""
    return max(0.0, float(now) - float(last_activity or 0.0))
