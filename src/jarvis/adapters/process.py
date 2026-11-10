"""Memory of this process on Windows: report it and hand idle pages back to the system."""
from __future__ import annotations

import ctypes
import gc
import logging
import sys
from ctypes import wintypes
from typing import Any

log = logging.getLogger("jarvis")


def _kernel32() -> Any:
    if sys.platform != "win32": raise OSError("process memory calls need Windows")
    return ctypes.windll.kernel32


def mem_info() -> dict[str, int]:
    """Working set / private commit of this process in MB (Windows)."""
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("a", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in ("pws", "ws", "a1", "a2", "a3", "a4", "pf", "ppf", "priv")]
    k = _kernel32(); k.GetCurrentProcess.restype = wintypes.HANDLE
    k.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    p: Any = PMC(); p.cb = ctypes.sizeof(p); k.K32GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return {"ws": p.ws >> 20, "priv": p.priv >> 20, "peak_ws": p.pws >> 20}


def mem_str() -> str:
    m = mem_info()
    return f"ws={m['ws']}MB priv={m['priv']}MB peak_ws={m['peak_ws']}MB"


def trim_memory() -> None:
    """Collect garbage and empty the working set; pages come back on demand."""
    gc.collect()
    try:
        k = _kernel32(); k.GetCurrentProcess.restype = wintypes.HANDLE
        k.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_ssize_t, ctypes.c_ssize_t]
        k.SetProcessWorkingSetSize(k.GetCurrentProcess(), -1, -1)
    except Exception as e: log.info("trim failed: %s", e)
    log.info("memory: %s", mem_str())
