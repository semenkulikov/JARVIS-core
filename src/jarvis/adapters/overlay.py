"""Cheat-sheet overlay in the style of the Game Bar «Производительность» widget.

Unpinned, it is a small dark rounded card: a normal clickable window that never steals focus,
dragged by its header, with pin, fold and close buttons and foldable sections. Pinned, it stays
on top as bare text on a transparent background and lets every click through (like a pinned
Game Bar widget); the pin hotkey brings it back. Position, pin and folded sections persist in a
small JSON file. The window lives on its own thread with its own Tk loop, so the listener never
waits for it; other threads only post messages. Global hotkeys use RegisterHotKey on a
message-loop thread. The text comes from jarvis.core.cheatsheet. Nothing is created on import.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import sys
import threading
from typing import Any, Callable, Mapping, Protocol, Sequence

from jarvis.core import cheatsheet as SHEET
from jarvis.core.cheatsheet import PanelState, Section

log = logging.getLogger("jarvis")
Config = Mapping[str, Any]
Content = Callable[[], tuple[Sequence[Section], Config]]
Binding = tuple[tuple[int, int], Callable[[], object]]
_WIN: Any = ctypes  # windll exists only on Windows

# Game Bar palette
CARD, HEADER, BORDER, HOVER, ACCENT = "#202020", "#2b2b2b", "#3a3a3a", "#2d2d2d", "#4cc2ff"
TEXT, MUTED, BUTTON_HOVER = "#ffffff", "#a8a8a8", "#3d3d3d"
KEY = "#010101"  # colour key of the pinned panel: these pixels are transparent; text edges blend into a dark outline
PIN_TEXT, PIN_MUTED, PIN_ACCENT = "#f2fff5", "#cfe9d6", "#7dffa8"
WIDTH_PHRASE, WIDTH_EFFECT, MIN_WIDTH, RADIUS = 200, 250, 360, 8
# Segoe Fluent Icons / MDL2 glyphs, with plain fallbacks
GLYPHS = {"icon": ("\ue720", "●"), "pin": ("\ue718", "📌"), "pinned": ("\ue841", "📍"), "close": ("\ue8bb", "✕"),
          "up": ("\ue70e", "▴"), "down": ("\ue70d", "▾"), "right": ("\ue76c", "▸")}


class Panel(Protocol):
    def post(self, message: tuple[str, Any]) -> None: ...


class Hotkey(Protocol):
    registered: list[bool]
    def stop(self) -> None: ...


class Overlay:
    """Show / hide / toggle / pin from any thread; the window is created on the first show.
    It is also the panel's event sink: pin, fold, move and close come back here and persist."""

    def __init__(self, content: Content, state_path: str | None = None, panel_factory: Callable[["Overlay"], Panel] | None = None,
                 hotkey_factory: Callable[[Sequence[Binding]], Hotkey] | None = None) -> None:
        self.content = content; self.state_path = state_path
        self.panel_factory = panel_factory or TkPanel; self.hotkey_factory = hotkey_factory or HotkeyThread
        self.lock = threading.RLock(); self.visible = False; self.panel: Panel | None = None; self.hotkey: Hotkey | None = None
        self.state = self._load()

    # ------------------------------------------------------------ state file
    def _load(self) -> PanelState:
        if not self.state_path or not os.path.exists(self.state_path): return PanelState()
        try:
            with open(self.state_path, encoding="utf-8") as f: return PanelState.from_json(json.load(f))
        except (OSError, ValueError) as e:
            log.warning("overlay state unreadable (%s), using defaults", type(e).__name__); return PanelState()

    def _save(self) -> None:
        if not self.state_path: return
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f: json.dump(self.state.to_json(), f, ensure_ascii=False)
            os.replace(tmp, self.state_path)
        except OSError as e: log.warning("overlay state not saved (%s)", type(e).__name__)

    # ------------------------------------------------------------ visibility
    def _panel(self) -> Panel:
        if self.panel is None: self.panel = self.panel_factory(self)
        return self.panel

    def _render(self) -> bool:
        sections, cfg = self.content()
        if not cfg.get("overlay_enabled", True): log.info("overlay disabled (overlay_enabled=false)"); return False
        with self.lock:
            self.visible = True; self._panel().post(("show", (list(sections), dict(cfg), self.state.copy())))
        return True

    def show(self) -> bool:
        if not self._render(): return False
        log.info("overlay shown (%s)", "pinned" if self.state.pinned else "unpinned")
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

    # ------------------------------------------------------------ panel events
    def toggle_pin(self) -> bool:
        """New pin state; a hidden panel is shown, so the hotkey always has a visible effect."""
        with self.lock:
            self.state.pinned = not self.state.pinned; self._save()
        log.info("overlay %s", "pinned" if self.state.pinned else "unpinned")
        self._render()
        return self.state.pinned

    def set_collapsed(self, key: str, collapsed: bool) -> None:
        with self.lock:
            self.state.collapsed[key] = collapsed; self._save()
        if self.visible: self._render()

    def moved(self, x: int, y: int) -> None:
        with self.lock:
            self.state.x, self.state.y = int(x), int(y); self._save()

    # ------------------------------------------------------------ hotkeys
    def start_hotkey(self, cfg: Config) -> bool:
        """Register the show/hide and pin hotkeys once; False when none could be registered."""
        if self.hotkey is not None or not cfg.get("overlay_enabled", True): return False
        specs = [(cfg.get("overlay_hotkey", SHEET.DEFAULTS["overlay_hotkey"]), self.toggle),
                 (cfg.get("overlay_pin_hotkey", SHEET.DEFAULTS["overlay_pin_hotkey"]), self.toggle_pin)]
        bindings: list[Binding] = []; names = []
        for spec, action in specs:
            keys = SHEET.parse_hotkey(spec)
            if keys is None: log.info("overlay hotkey off or invalid: %r", spec); continue
            bindings.append((keys, action)); names.append(str(spec))
        if not bindings: return False
        self.hotkey = self.hotkey_factory(bindings)
        for name, ok in zip(names, self.hotkey.registered, strict=False):
            log.info("overlay hotkey %s %s", name, "registered" if ok else "NOT registered (taken?)")
        return any(self.hotkey.registered)


class HotkeyThread:
    """RegisterHotKey on a dedicated thread with its own message loop; WM_HOTKEY runs the bound action."""

    WM_HOTKEY, WM_QUIT, BASE_ID = 0x0312, 0x0012, 0x4A52

    def __init__(self, bindings: Sequence[Binding]) -> None:
        self.bindings = list(bindings); self.registered = [False] * len(self.bindings); self.tid = 0; self.ready = threading.Event()
        if sys.platform != "win32": self.ready.set(); return
        threading.Thread(target=self._run, name="overlay-hotkey", daemon=True).start()
        self.ready.wait(2.0)

    def _run(self) -> None:
        from ctypes import wintypes
        u = _WIN.windll.user32; self.tid = int(_WIN.windll.kernel32.GetCurrentThreadId())
        for i, (keys, _) in enumerate(self.bindings): self.registered[i] = bool(u.RegisterHotKey(None, self.BASE_ID + i, keys[0], keys[1]))
        self.ready.set()
        if not any(self.registered): return
        msg = wintypes.MSG()
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                i = int(msg.wParam) - self.BASE_ID
                if msg.message == self.WM_HOTKEY and 0 <= i < len(self.bindings):
                    try: self.bindings[i][1]()
                    except Exception as e: log.warning("overlay hotkey action failed (%s)", type(e).__name__)
        finally:
            for i, ok in enumerate(self.registered):
                if ok: u.UnregisterHotKey(None, self.BASE_ID + i)

    def stop(self) -> None:
        if any(self.registered) and self.tid: _WIN.windll.user32.PostThreadMessageW(self.tid, self.WM_QUIT, 0, 0)


class TkPanel:
    """The real window, owned by its own thread; ``post`` is the only thread-safe entry."""

    def __init__(self, events: Overlay) -> None:
        self.events = events; self.queue: queue.Queue[tuple[str, Any]] = queue.Queue(); self.root: Any = None
        self.fonts: dict[str, Any] = {}; self.icons = False; self.drag: tuple[int, int] | None = None
        threading.Thread(target=self._run, name="overlay", daemon=True).start()

    def post(self, message: tuple[str, Any]) -> None: self.queue.put(message)

    def _run(self) -> None:
        try:
            if sys.platform == "win32":
                try: _WIN.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: crisp text
                except Exception: pass
            import tkinter as tk
            root = tk.Tk(); root.withdraw(); root.overrideredirect(True); root.attributes("-topmost", True)
            root.configure(bg=CARD); root.title("Jarvis"); self.root = root
            root.after(50, self._poll); root.mainloop()
        except Exception as e: log.warning("overlay window unavailable (%s)", type(e).__name__)

    def _poll(self) -> None:
        while True:
            try: kind, data = self.queue.get_nowait()
            except queue.Empty: break
            try:
                if kind == "show": self._render(*data)
                elif kind == "hide": self.root.withdraw()
            except Exception as e: log.warning("overlay %s failed (%s: %s)", kind, type(e).__name__, e)
        self.root.after(60, self._poll)

    # ------------------------------------------------------------ look
    def _pick_fonts(self, cfg: Config) -> None:
        import tkinter.font as tkfont
        fams = set(tkfont.families(self.root))
        def first(*names: str) -> str: return next((n for n in names if n in fams), names[-1])
        custom = str(cfg.get("overlay_font") or "")
        base = custom if custom and custom != SHEET.DEFAULTS["overlay_font"] else first("Segoe UI Variable Text", "Segoe UI", "TkDefaultFont")
        semi = first(base + " Semibold", "Segoe UI Variable Text Semibold", "Segoe UI Semibold", base)
        size = int(cfg.get("overlay_font_size", SHEET.DEFAULTS["overlay_font_size"]))
        icon = first("Segoe Fluent Icons", "Segoe MDL2 Assets", "")
        self.icons = bool(icon)
        self.fonts = {"text": (base, size), "small": (base, max(7, size - 1)), "semi": (semi, size), "title": (semi, size + 1),
                      "section": (semi, size), "icon": (icon or base, size), "button": (icon or base, size)}

    def _glyph(self, name: str) -> str: return GLYPHS[name][0 if self.icons else 1]

    def _render(self, sections: Sequence[Section], cfg: Config, state: PanelState) -> None:
        import tkinter as tk
        root = self.root; pinned = state.pinned
        if not self.fonts: self._pick_fonts(cfg)
        for w in root.winfo_children(): w.destroy()
        root.unbind_all("<MouseWheel>")
        bg = KEY if pinned else CARD
        root.configure(bg=bg)
        try: root.attributes("-transparentcolor", KEY if pinned else "")
        except tk.TclError: pass  # not on Windows
        outer = tk.Frame(root, bg=KEY if pinned else BORDER, padx=0 if pinned else 1, pady=0 if pinned else 1); outer.pack(fill="both", expand=True)
        card = tk.Frame(outer, bg=bg); card.pack(fill="both", expand=True)
        folded = state.is_collapsed(SHEET.PANEL_KEY)
        self._header(card, state, folded)
        if not folded: self._body(card, sections, state)
        root.update_idletasks()
        left, top, aw, ah = _work_area(root)
        margin = int(cfg.get("overlay_margin_px", SHEET.DEFAULTS["overlay_margin_px"]))
        w, h = max(MIN_WIDTH, root.winfo_reqwidth()), root.winfo_reqheight()
        if state.x is None or state.y is None:
            x, y = SHEET.position(SHEET.corner(cfg), (w, h), (aw, ah), margin); x, y = left + x, top + y
        else: x, y = SHEET.clamp((state.x, state.y), (w, h), (left, top, aw, ah))
        root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        root.deiconify(); root.attributes("-topmost", True); root.update_idletasks()
        _style(root, pinned, (w, h))
        root.attributes("-alpha", SHEET.opacity(cfg) if pinned else 1.0)

    def _header(self, card: Any, state: PanelState, folded: bool) -> None:
        import tkinter as tk
        pinned = state.pinned; hb = KEY if pinned else HEADER; fg = PIN_ACCENT if pinned else TEXT
        head = tk.Frame(card, bg=hb, padx=10, pady=6); head.pack(fill="x")
        icon = tk.Label(head, text=self._glyph("icon"), font=self.fonts["icon"], fg=PIN_ACCENT if pinned else ACCENT, bg=hb)
        icon.pack(side="left", padx=(0, 8))
        title = tk.Label(head, text=SHEET.TITLE, font=self.fonts["title"], fg=fg, bg=hb); title.pack(side="left")
        if pinned: return  # clicks pass through a pinned panel: no buttons, the pin hotkey unpins
        for name, action in (("close", self.events.hide),
                             ("down" if folded else "up", lambda: self.events.set_collapsed(SHEET.PANEL_KEY, not folded)),
                             ("pin", self.events.toggle_pin)):
            self._button(head, name, action)
        for w in (head, icon, title):
            w.bind("<ButtonPress-1>", self._drag_start); w.bind("<B1-Motion>", self._drag_move); w.bind("<ButtonRelease-1>", self._drag_end)

    def _button(self, parent: Any, glyph: str, action: Callable[[], object]) -> None:
        import tkinter as tk
        b = tk.Label(parent, text=self._glyph(glyph), font=self.fonts["button"], fg=TEXT, bg=HEADER, padx=7, pady=2, cursor="hand2")
        b.pack(side="right", padx=(2, 0))
        b.bind("<Enter>", lambda e: b.configure(bg=BUTTON_HOVER)); b.bind("<Leave>", lambda e: b.configure(bg=HEADER))
        b.bind("<ButtonRelease-1>", lambda e: action())

    def _body(self, card: Any, sections: Sequence[Section], state: PanelState) -> None:
        import tkinter as tk
        pinned = state.pinned; bg = KEY if pinned else CARD
        _, _, _, ah = _work_area(self.root)
        canvas = tk.Canvas(card, bg=bg, highlightthickness=0, bd=0); canvas.pack(fill="both", expand=True)
        body = tk.Frame(canvas, bg=bg, padx=6, pady=6); canvas.create_window(0, 0, window=body, anchor="nw")
        for s in sections:
            folded = state.is_collapsed(s.key or s.title)
            self._section_header(body, s, folded, pinned)
            if folded: continue
            for ln in s.lines: self._row(body, ln, pinned)
        body.update_idletasks()
        bw, bh = body.winfo_reqwidth(), body.winfo_reqheight()
        limit = max(200, ah - 80)  # header and margins
        canvas.configure(width=max(bw, MIN_WIDTH - 2), height=min(bh, limit), scrollregion=(0, 0, bw, bh))
        if bh > limit and not pinned:
            self.root.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units"))

    def _section_header(self, body: Any, s: Section, folded: bool, pinned: bool) -> None:
        import tkinter as tk
        bg = KEY if pinned else CARD
        row = tk.Frame(body, bg=bg, padx=4, pady=3); row.pack(fill="x", pady=(6, 1))
        chev = tk.Label(row, text=self._glyph("right" if folded else "down"), font=self.fonts["small"], fg=PIN_MUTED if pinned else MUTED, bg=bg)
        chev.pack(side="left", padx=(0, 6))
        title = tk.Label(row, text=s.title, font=self.fonts["section"], fg=PIN_ACCENT if pinned else TEXT, bg=bg); title.pack(side="left")
        count = tk.Label(row, text=str(len(s.lines)), font=self.fonts["small"], fg=PIN_MUTED if pinned else MUTED, bg=bg)
        count.pack(side="right")
        if pinned: return
        widgets = (row, chev, title, count); key = s.key or s.title

        def fold(_e: Any) -> None: self.events.set_collapsed(key, not folded)
        for w in widgets: w.bind("<ButtonRelease-1>", fold); w.configure(cursor="hand2")
        _hover(row, widgets, (CARD, HOVER), None)

    def _row(self, body: Any, ln: SHEET.Line, pinned: bool) -> None:
        import tkinter as tk
        bg = KEY if pinned else CARD
        row = tk.Frame(body, bg=bg); row.pack(fill="x")
        bar = tk.Frame(row, bg=bg, width=3); bar.pack(side="left", fill="y")
        inner = tk.Frame(row, bg=bg, padx=10, pady=2); inner.pack(side="left", fill="x", expand=True)
        phrase = tk.Label(inner, text=ln.phrase, font=self.fonts["semi"], fg=PIN_TEXT if pinned else TEXT, bg=bg, justify="left",
                          anchor="nw", wraplength=WIDTH_PHRASE, width=0)
        phrase.grid(row=0, column=0, sticky="nw", padx=(0, 12))
        inner.grid_columnconfigure(0, minsize=WIDTH_PHRASE)
        widgets = [row, inner, phrase]
        if ln.effect:
            eff = tk.Label(inner, text=ln.effect, font=self.fonts["text"], fg=PIN_MUTED if pinned else MUTED, bg=bg, justify="left",
                           anchor="nw", wraplength=WIDTH_EFFECT)
            eff.grid(row=0, column=1, sticky="nw"); widgets.append(eff)
        if not pinned: _hover(row, widgets, (CARD, HOVER), bar)

    # ------------------------------------------------------------ drag
    def _drag_start(self, e: Any) -> None: self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e: Any) -> None:
        if self.drag: self.root.geometry("+%d+%d" % (e.x_root - self.drag[0], e.y_root - self.drag[1]))

    def _drag_end(self, e: Any) -> None:
        if self.drag: self.drag = None; self.events.moved(self.root.winfo_x(), self.root.winfo_y())


def _hover(row: Any, widgets: Sequence[Any], colours: tuple[str, str], bar: Any) -> None:
    """Game Bar style highlight: lighter row and an accent bar while the pointer is inside the row."""
    normal, lit = colours
    def paint(on: bool) -> None:
        for w in widgets: w.configure(bg=lit if on else normal)
        if bar is not None: bar.configure(bg=ACCENT if on else normal)
    def leave(e: Any) -> None:
        inside = row.winfo_containing(e.x_root, e.y_root)
        if inside is None or not str(inside).startswith(str(row)): paint(False)
    for w in widgets: w.bind("<Enter>", lambda e: paint(True), add="+"); w.bind("<Leave>", leave, add="+")


def _work_area(root: Any) -> tuple[int, int, int, int]:
    """Desktop without the taskbar (left, top, width, height); the whole screen off Windows."""
    if sys.platform == "win32":
        try:
            class RECT(ctypes.Structure): _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
            r = RECT()
            if _WIN.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0): return r.l, r.t, r.r - r.l, r.b - r.t  # SPI_GETWORKAREA
        except Exception: pass
    return 0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight())


GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = -20, 0x20, 0x80, 0x80000, 0x08000000


DWMWA_WINDOW_CORNER_PREFERENCE, DWMWA_BORDER_COLOR, DWMWCP_DONOTROUND, DWMWCP_ROUND = 33, 34, 1, 2
DWMWA_COLOR_DEFAULT, DWMWA_COLOR_NONE = 0xFFFFFFFF, 0xFFFFFFFE


def _dwm(hwnd: int, attr: int, value: int) -> bool:
    v = ctypes.c_uint(value)
    try: return bool(_WIN.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4) == 0)
    except Exception: return False


def _style(root: Any, pinned: bool, size: tuple[int, int]) -> None:
    """No taskbar button and never activated; pinned also lets every click through; unpinned gets rounded corners."""
    if sys.platform != "win32": return
    u = _WIN.windll.user32
    hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
    ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    ex = ex | WS_EX_TRANSPARENT | WS_EX_LAYERED if pinned else ex & ~WS_EX_TRANSPARENT
    u.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    # Windows 11 frame: rounded with the system border when unpinned; square and borderless when pinned
    ok = _dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND if pinned else DWMWCP_ROUND)
    _dwm(hwnd, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE if pinned else DWMWA_COLOR_DEFAULT)
    if pinned: u.SetWindowRgn(hwnd, None, True); return
    if not ok:  # Windows 10: clip to a rounded region
        u.SetWindowRgn(hwnd, _WIN.windll.gdi32.CreateRoundRectRgn(0, 0, size[0] + 1, size[1] + 1, RADIUS * 2, RADIUS * 2), True)
