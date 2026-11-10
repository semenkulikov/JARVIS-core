# Laptop control + extra quick-command helpers for Jarvis
import os, re, ctypes, subprocess, threading, time, difflib, logging
from ctypes import wintypes
log = logging.getLogger("jarvis")

VK = {"vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD, "next": 0xB0, "prev": 0xB1, "play": 0xB3}

def press(vk, times=1):
    u = ctypes.windll.user32
    for _ in range(times):
        u.keybd_event(vk, 0, 0, 0); u.keybd_event(vk, 0, 2, 0); time.sleep(0.02)
    log.info("keys sent: vk=0x%X x%d", vk, times)

def monitor_off():
    u = ctypes.windll.user32
    u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
    r = u.SendMessageTimeoutW(0xFFFF, 0x0112, 0xF170, 2, 0x0002, 1000, None)
    log.info("monitor off sent (%s)", r)

class SPS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte), ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_byte), ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

def battery():
    s = SPS(); ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
    pct = s.BatteryLifePercent & 0xFF
    return (None if pct == 255 else pct), s.ACLineStatus == 1

def temperature_c():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation | Measure-Object -Property HighPrecisionTemperature -Maximum).Maximum"],
                             capture_output=True, text=True, timeout=20, creationflags=0x08000000).stdout.strip()
        v = float(out.replace(",", "."))
        return round(v / 10 - 273.15)
    except Exception as e:
        log.warning("temperature read failed: %s", e); return None

# ---------- Russian number parsing ----------
_NUM = {"ноль": 0, "один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
        "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
        "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20,
        "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
        "сто": 100, "двести": 200, "триста": 300, "полтора": 1.5, "полторы": 1.5}

def parse_duration_s(text):
    t = text.lower().replace("ё", "е")
    if "полчаса" in t: return 1800
    m = re.search(r"(\d+)", t); n = None
    if m: n = float(m.group(1))
    else:
        acc = 0; found = False
        for w in t.split():
            if w in _NUM: acc += _NUM[w]; found = True
            elif found: break
        if found: n = acc
    unit = 60
    if re.search(r"секунд", t): unit = 1
    elif re.search(r"\bчас", t): unit = 3600
    if n is None:
        if re.search(r"\b(минуту|секунду|час)\b", t): n = 1
        else: return None
    return int(n * unit)

# ---------- projects ----------
from jarvis_paths import PROJECTS_DIR
PROJ_DIR = str(PROJECTS_DIR)

def _spoken(name, latin_fn):
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+|[А-Яа-яЁё]+", name)
    return " ".join(latin_fn(p).lower() for p in parts)

def find_project(spoken, latin_fn):
    spoken = re.sub(r"\s+", "", spoken.lower().replace("ё", "е"))
    if not spoken: return None, 0
    best, bs = None, 0
    for d in (os.listdir(PROJ_DIR) if os.path.isdir(PROJ_DIR) else []):
        p = os.path.join(PROJ_DIR, d)
        if not os.path.isdir(p): continue
        cands = [re.sub(r"\s+", "", _spoken(d, latin_fn)), d.lower()]
        s = max(difflib.SequenceMatcher(None, spoken, c).ratio() for c in cands)
        if s > bs: best, bs = p, s
    return best, bs

def recent_repo():
    best, bt = None, 0
    for d in (os.listdir(PROJ_DIR) if os.path.isdir(PROJ_DIR) else []):
        g = os.path.join(PROJ_DIR, d, ".git")
        if not os.path.isdir(g): continue
        t = max([os.path.getmtime(x) for x in [os.path.join(g, f) for f in ("index", "HEAD", "FETCH_HEAD", "ORIG_HEAD", "logs")] if os.path.exists(x)] or [0])
        if t > bt: best, bt = os.path.join(PROJ_DIR, d), t
    return best

def remote_url(repo):
    try:
        u = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10, creationflags=0x08000000).stdout.strip()
    except Exception as e:
        log.warning("git remote failed: %s", e); return None
    if not u: return None
    m = re.match(r"git@([^:]+):(.+?)(\.git)?$", u)
    if m: return f"https://{m.group(1)}/{m.group(2)}"
    return re.sub(r"\.git$", "", re.sub(r"https://[^@/]+@", "https://", u))

def cursor_exe():
    for p in [os.path.expandvars(r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe"), r"C:\Program Files\Cursor\Cursor.exe"]:
        if os.path.exists(p): return p
    return None

# ---------- timers ----------
class Timers:
    def __init__(self): self.items = []; self.fired = []; self.lock = threading.Lock()
    def add(self, secs, label):
        t = threading.Timer(secs, self._fire, args=(label,)); t.daemon = True
        with self.lock: self.items.append(t)
        t.start(); log.info("timer set: %ss (%s)", secs, label)
    def _fire(self, label):
        with self.lock:
            self.fired.append(label); self.items = [x for x in self.items if x.is_alive() and x is not threading.current_thread()]
        log.info("timer fired: %s", label)
    def cancel(self):
        with self.lock:
            n = len([x for x in self.items if x.is_alive()])
            for x in self.items: x.cancel()
            self.items = []
        log.info("timers cancelled: %d", n); return n
    def pop_fired(self):
        with self.lock:
            f = self.fired; self.fired = []; return f
TIMERS = Timers()
