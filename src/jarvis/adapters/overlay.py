"""Cheat-sheet overlay: a small translucent, always-on-top, click-through panel in a screen corner.

Like the Game Bar performance overlay: dark, frameless, it never takes focus or clicks. The panel
lives on its own thread with its own Tk loop, so the listener never waits for it; other threads
only post «show» / «hide». A global hotkey (RegisterHotKey on a message-loop thread) toggles it.
The text comes from jarvis.core.cheatsheet. Nothing is created on import.
"""
from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
from typing import Any, Callable, Mapping, Protocol, Sequence

from jarvis.core import cheatsheet as SHEET
from jarvis.core.cheatsheet import Section

log = logging.getLogger("jarvis")
Config = Mapping[str, Any]
Content = Callable[[], tuple[Sequence[Section], Config]]
_WIN: Any = ctypes  # windll exists only on Windows

BG, RULE = "#0e1217", "#25313d"
TITLE_FG, ACCENT, PHRASE_FG, EFFECT_FG = "#7d8b99", "#4fc3f7", "#eef3f7", "#a3b0bc"
WIDTH_PHRASE, WIDTH_EFFECT = 190, 250


class Panel(Protocol):
    def post(self, message: tuple[str, Any]) -> None: ...


class Hotkey(Protocol):
    registered: bool
    def stop(self) -> None: ...


class Overlay:
    """Show / hide / toggle from any thread; the window is created on the first show."""

    def __init__(self, content: Content, panel_factory: Callable[[], Panel] | None = None,
                 hotkey_factory: Callable[[tuple[int, int], Callable[[], object]], Hotkey] | None = None) -> None:
        self.content = content; self.panel_factory = panel_factory or TkPanel; self.hotkey_factory = hotkey_factory or HotkeyThread
        self.lock = threading.Lock(); self.visible = False; self.panel: Panel | None = None; self.hotkey: Hotkey | None = None

    def _panel(self) -> Panel:
        if self.panel is None: self.panel = self.panel_factory()
        return self.panel

    def show(self) -> bool:
        sections, cfg = self.content()
        if not cfg.get("overlay_enabled", True): log.info("overlay disabled (overlay_enabled=false)"); return False
        with self.lock:
            self.visible = True; self._panel().post(("show", (list(sections), dict(cfg))))
        log.info("overlay shown: %d sections, %d lines", len(sections), sum(len(s.lines) for s in sections))
        return True

    def hide(self) -> bool:
        with self.lock:
            was = self.visible; self.visible = False
            if self.panel is not None: self.panel.post(("hide", None))
        if was: log.info("overlay hidden")
        return was

    def toggle(self) -> bool:
        """New visibility."""
        if self.visible: self.hide(); return False
        return self.show()

    def start_hotkey(self, cfg: Config) -> bool:
        """Register the global toggle hotkey once; False when off, invalid or taken by another program."""
        if self.hotkey is not None or not cfg.get("overlay_enabled", True): return False
        keys = SHEET.parse_hotkey(cfg.get("overlay_hotkey", SHEET.DEFAULTS["overlay_hotkey"]))
        if keys is None: log.info("overlay hotkey off or invalid: %r", cfg.get("overlay_hotkey")); return False
        self.hotkey = self.hotkey_factory(keys, self.toggle)
        log.info("overlay hotkey %s %s", cfg.get("overlay_hotkey"), "registered" if self.hotkey.registered else "NOT registered (taken?)")
        return self.hotkey.registered


class HotkeyThread:
    """RegisterHotKey on a dedicated thread with its own message loop; WM_HOTKEY calls ``callback``."""

    WM_HOTKEY, WM_QUIT, ID = 0x0312, 0x0012, 0x4A52

    def __init__(self, keys: tuple[int, int], callback: Callable[[], object]) -> None:
        self.keys = keys; self.callback = callback; self.registered = False; self.tid = 0; self.ready = threading.Event()
        if sys.platform != "win32": self.ready.set(); return
        threading.Thread(target=self._run, name="overlay-hotkey", daemon=True).start()
        self.ready.wait(2.0)

    def _run(self) -> None:
        u = _WIN.windll.user32; k = _WIN.windll.kernel32
        self.tid = int(k.GetCurrentThreadId())
        self.registered = bool(u.RegisterHotKey(None, self.ID, self.keys[0], self.keys[1])); self.ready.set()
        if not self.registered: return
        from ctypes import wintypes
        msg = wintypes.MSG()
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY:
                    try: self.callback()
                    except Exception as e: log.warning("overlay hotkey action failed (%s)", type(e).__name__)
        finally: u.UnregisterHotKey(None, self.ID)

    def stop(self) -> None:
        if self.registered and self.tid: _WIN.windll.user32.PostThreadMessageW(self.tid, self.WM_QUIT, 0, 0)


class TkPanel:
    """The real window, owned by its own thread; ``post`` is the only thread-safe entry."""

    def __init__(self) -> None:
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue(); self.root: Any = None
        threading.Thread(target=self._run, name="overlay", daemon=True).start()

    def post(self, message: tuple[str, Any]) -> None: self.queue.put(message)

    def _run(self) -> None:
        try:
            if sys.platform == "win32":
                try: _WIN.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: crisp text
                except Exception: pass
            import tkinter as tk
            root = tk.Tk(); root.withdraw(); root.overrideredirect(True); root.attributes("-topmost", True)
            root.configure(bg=BG); root.title("Jarvis cheat sheet"); self.root = root
            root.after(50, self._poll); root.mainloop()
        except Exception as e: log.warning("overlay window unavailable (%s)", type(e).__name__)

    def _poll(self) -> None:
        while True:
            try: kind, data = self.queue.get_nowait()
            except queue.Empty: break
            try:
                if kind == "show": self._render(*data)
                elif kind == "hide": self.root.withdraw()
            except Exception as e: log.warning("overlay %s failed (%s)", kind, type(e).__name__)
        self.root.after(80, self._poll)

    def _render(self, sections: Sequence[Section], cfg: Config) -> None:
        import tkinter as tk
        root = self.root
        for w in root.winfo_children(): w.destroy()
        size = int(cfg.get("overlay_font_size", SHEET.DEFAULTS["overlay_font_size"]))
        family = str(cfg.get("overlay_font") or SHEET.DEFAULTS["overlay_font"])
        font, small = (family, size), (family, max(7, size - 1))
        bold = (family + " Semibold", size) if family == "Segoe UI" else (family, size, "bold")
        box = tk.Frame(root, bg=BG, padx=14, pady=10); box.pack()
        head = tk.Frame(box, bg=BG); head.grid(row=0, column=0, columnspan=2, sticky="we")
        tk.Label(head, text=SHEET.TITLE.upper(), font=(small[0], small[1], "bold"), fg=TITLE_FG, bg=BG).pack(side="left")
        hint = str(cfg.get("overlay_hotkey") or "").replace("+", " + ").title() or SHEET.HINT_HIDE
        tk.Label(head, text=hint, font=small, fg=TITLE_FG, bg=BG).pack(side="right", padx=(16, 0))
        row = 1
        for s in sections:
            tk.Label(box, text=s.title, font=(bold[0], size + 1), fg=ACCENT, bg=BG).grid(row=row, column=0, columnspan=2, sticky="w", pady=(9, 2))
            tk.Frame(box, bg=RULE, height=1).grid(row=row + 1, column=0, columnspan=2, sticky="we", pady=(0, 4)); row += 2
            for ln in s.lines:
                tk.Label(box, text=ln.phrase, font=bold, fg=PHRASE_FG, bg=BG, justify="left", anchor="nw",
                         wraplength=WIDTH_PHRASE).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=1)
                tk.Label(box, text=ln.effect, font=font, fg=EFFECT_FG, bg=BG, justify="left", anchor="nw",
                         wraplength=WIDTH_EFFECT).grid(row=row, column=1, sticky="nw", pady=1)
                row += 1
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        left, top, sw, sh = _work_area(root)
        x, y = SHEET.position(SHEET.corner(cfg), (w, h), (sw, sh), int(cfg.get("overlay_margin_px", SHEET.DEFAULTS["overlay_margin_px"])))
        root.geometry("%dx%d+%d+%d" % (w, h, left + x, top + y))
        root.deiconify(); root.attributes("-topmost", True)
        _click_through(root); root.attributes("-alpha", SHEET.opacity(cfg))


def _work_area(root: Any) -> tuple[int, int, int, int]:
    """Desktop without the taskbar (left, top, width, height); the whole screen off Windows."""
    if sys.platform == "win32":
        try:
            class RECT(ctypes.Structure): _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
            r = RECT()
            if _WIN.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0): return r.l, r.t, r.r - r.l, r.b - r.t  # SPI_GETWORKAREA
        except Exception: pass
    return 0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight())


def _click_through(root: Any) -> None:
    """Layered + transparent to the mouse + tool window (no taskbar button) + never activated."""
    if sys.platform != "win32": return
    u = _WIN.windll.user32
    hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
    ex = u.GetWindowLongW(hwnd, -20)
    u.SetWindowLongW(hwnd, -20, ex | 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000)
