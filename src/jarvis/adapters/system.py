"""Desktop actions behind one backend, so tests substitute a fake and nothing real runs."""
from __future__ import annotations

import base64
import ctypes
import datetime
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from jarvis.adapters import laptop as LAPTOP
from jarvis.core import codemode as CODE
from jarvis.core import text as JT

# Windows-only ctypes and os entry points (absent from the Linux stubs mypy also checks against).
_WIN: Any = ctypes
_WIN_OS: Any = os
# Never closed by a protocol, whatever close_apps lists: Jarvis itself, its terminal and the shell.
# Kept when «close everything»: Jarvis, the shell and system UI hosts; user terminals are closed too.
SHELL_PROCESSES = frozenset({"python", "pythonw", "py", "pyw", "explorer", "dwm", "winlogon", "csrss", "logonui", "lockapp",
                             "shellexperiencehost", "startmenuexperiencehost", "searchhost", "searchapp", "textinputhost",
                             "systemsettingsbroker", "applicationframehost"})
PROTECTED_PROCESSES = frozenset({"python", "pythonw", "py", "pyw", "cmd", "powershell", "pwsh", "windowsterminal", "conhost",
                                 "openconsole", "wt", "explorer", "dwm", "winlogon", "csrss"})
CREATE_NEW_CONSOLE = 0x00000010
# Default-terminal console owner used by Windows 11 when Windows Terminal is selected.
WT_DELEGATION_CONSOLE = "2EACA947-7F5F-4CFA-BA87-8F7FBEEFBE69"
TERMINAL_WINDOW_CLASSES = frozenset({"CASCADIA_HOSTING_WINDOW_CLASS", "ConsoleWindowClass"})


def _windows_terminal_is_default() -> bool:
    """True when this Windows user picked Windows Terminal as the default terminal app."""
    if os.name != "nt": return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Console\%%Startup") as key:
            value, _ = winreg.QueryValueEx(key, "DelegationConsole")
        return str(value).upper().replace("{", "").replace("}", "") == WT_DELEGATION_CONSOLE
    except OSError:
        return False


def _wt_exe() -> str | None:
    found = shutil.which("wt.exe") or shutil.which("wt")
    if found: return found
    alias = Path(os.environ.get("LOCALAPPDATA") or "") / "Microsoft" / "WindowsApps" / "wt.exe"
    return str(alias) if alias.is_file() else None



class SystemBackend:
    """The real Windows desktop: Core Audio, clipboard, OCR, screenshots, windows, shutdown and git."""

    is_fake=False
    def _run(self, args: list[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args,capture_output=True,text=True,timeout=timeout,creationflags=0x08000000 if os.name=='nt' else 0)
    def mute(self, muted: bool) -> None:self._audio('mute',bool(muted))
    def volume(self, value: float) -> None:self._audio('volume',float(value)/100)
    def output_volume(self) -> float | None:
        """Windows level (0..100) of the default speakers, read only; None when Core Audio is unavailable."""
        try:
            level=self._audio('get',0.0)
            return None if level is None else level*100
        except Exception:return None
    def input_volume(self) -> float | None:
        """Windows level (0..1) of the default microphone, read only; None when Core Audio is unavailable."""
        try:return self._audio('get',0.0,flow=1)
        except Exception:return None  # logging aid only: never break the listener over it
    def _audio(self, mode: str, value: float, flow: int = 0) -> float | None:
        class GUID(ctypes.Structure):_fields_=[('d1',ctypes.c_uint32),('d2',ctypes.c_uint16),('d3',ctypes.c_uint16),('d4',ctypes.c_ubyte*8)]
        def guid(s: str) -> GUID:return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)
        def method(ptr: Any, slot: int, *argtypes: Any) -> Any:
            addr=ctypes.cast(ptr,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[slot]
            return _WIN.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,*argtypes)(addr)
        def check(hr: int) -> None:
            if hr<0:raise OSError('CoreAudio_call_failed')
        ole=_WIN.WinDLL('ole32');ole.CoInitializeEx.argtypes=[ctypes.c_void_p,ctypes.c_uint];ole.CoInitializeEx.restype=ctypes.c_long
        ole.CoCreateInstance.argtypes=[ctypes.POINTER(GUID),ctypes.c_void_p,ctypes.c_uint,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)];ole.CoCreateInstance.restype=ctypes.c_long
        hr=ole.CoInitializeEx(None,2);initialized=hr in (0,1)
        if hr not in (0,1,-2147417850):check(hr)
        enum=ctypes.c_void_p();device=ctypes.c_void_p();volume=ctypes.c_void_p()
        try:
            cls=guid('BCDE0395-E52F-467C-8E3D-C4579291692E');iid=guid('A95664D2-9614-4F35-A746-DE8DB63617E6')
            check(ole.CoCreateInstance(ctypes.byref(cls),None,23,ctypes.byref(iid),ctypes.byref(enum)))
            check(method(enum,4,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p))(enum,flow,1,ctypes.byref(device)))
            iid=guid('5CDF2C82-841E-4546-9722-0CF74078229A')
            check(method(device,3,ctypes.POINTER(GUID),ctypes.c_uint,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p))(device,ctypes.byref(iid),23,None,ctypes.byref(volume)))
            if mode=='mute':check(method(volume,14,ctypes.c_int,ctypes.c_void_p)(volume,int(value),None))
            elif mode=='get':
                level=ctypes.c_float();check(method(volume,9,ctypes.POINTER(ctypes.c_float))(volume,ctypes.byref(level)));return float(level.value)
            else:check(method(volume,7,ctypes.c_float,ctypes.c_void_p)(volume,value,None))
        finally:
            for ptr in (volume,device,enum):
                if ptr:method(ptr,2)(ptr)
            if initialized:ole.CoUninitialize()
        return None
    def clipboard(self, limit: int) -> tuple[str, bool]:
        u=_WIN.windll.user32;k=_WIN.windll.kernel32
        u.GetClipboardData.restype=ctypes.c_void_p;k.GlobalLock.argtypes=[ctypes.c_void_p];k.GlobalLock.restype=ctypes.c_void_p;k.GlobalSize.argtypes=[ctypes.c_void_p];k.GlobalSize.restype=ctypes.c_size_t;k.GlobalUnlock.argtypes=[ctypes.c_void_p]
        for _ in range(10):
            if u.OpenClipboard(None):break
            time.sleep(.02)
        else:raise OSError('clipboard_busy')
        try:
            h=u.GetClipboardData(13)
            if not h:return '',False
            ptr=k.GlobalLock(h)
            if not ptr:raise OSError('clipboard_lock_failed')
            try:text=ctypes.string_at(ptr,min(k.GlobalSize(h),2*(limit+2))).decode('utf-16-le',errors='replace').split('\x00',1)[0]
            finally:k.GlobalUnlock(h)
            return text[:limit],len(text)>limit
        finally:u.CloseClipboard()
    def window_ocr(self, limit: int) -> tuple[str, bool]:
        r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(CODE.WINDOW_OCR_PS.encode('utf-16le')).decode()],capture_output=True,timeout=30,creationflags=0x08000000 if os.name=='nt' else 0)
        if r.returncode:raise OSError('ocr_failed')
        text='\n'.join(x.strip() for x in r.stdout.decode('utf-8','replace').splitlines() if x.strip())
        return text[:limit],len(text)>limit
    def screenshot(self, folder: str | os.PathLike[str]) -> str:
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);target=folder/('jarvis_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]+'.png')
        q=str(target).replace("'","''")
        script="Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; $r=[Windows.Forms.SystemInformation]::VirtualScreen; $b=New-Object Drawing.Bitmap($r.Width,$r.Height); $g=[Drawing.Graphics]::FromImage($b); try {$g.CopyFromScreen($r.Left,$r.Top,0,0,$b.Size); $b.Save('"+q+"',[Drawing.Imaging.ImageFormat]::Png)} finally {$g.Dispose();$b.Dispose()}"
        r=self._run(['powershell.exe','-NoProfile','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()])
        if r.returncode or not target.exists():raise OSError('screenshot_failed')
        return str(target)
    def disk(self, drive: str) -> tuple[int, int, str]:
        drive={'ц':'c','цэ':'c','си':'c','д':'d','дэ':'d','ди':'d','е':'e','и':'e'}.get(drive,drive)
        if not re.fullmatch('[a-z]',drive):raise ValueError('invalid_drive')
        info=shutil.disk_usage(drive.upper()+':\\');return info.free,info.total,drive.upper()
    def close_window(self) -> None:
        u=_WIN.windll.user32;u.GetForegroundWindow.restype=ctypes.c_void_p;h=u.GetForegroundWindow()
        u.GetClassNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int];buf=ctypes.create_unicode_buffer(256);u.GetClassNameW(h,buf,256)
        if not h or buf.value in ('Progman','WorkerW','Shell_TrayWnd'):raise ValueError('no_user_window')
        pid=ctypes.c_ulong();u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];u.GetWindowThreadProcessId(h,ctypes.byref(pid))
        if pid.value==os.getpid():raise ValueError('refuse_self_close')
        u.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
        if not u.PostMessageW(h,0x10,0,0):raise OSError('window_close_failed')
    def media(self, play: bool = False) -> None:
        u=_WIN.windll.user32;u.SendMessageTimeoutW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
        u.SendMessageTimeoutW(0xFFFF,0x319,0,(46 if play else 47)<<16,2,1000,None)
    def monitor_off(self) -> None:
        LAPTOP.monitor_off()
    def lock(self) -> None:
        r=self._run(['rundll32.exe','user32.dll,LockWorkStation'])
        if r.returncode:raise OSError('lock_failed')
    def shutdown(self, seconds: float) -> None:
        r=self._run(['shutdown.exe','/s','/t',str(int(seconds))])
        if r.returncode:raise OSError('shutdown_schedule_failed')
    def shutdown_cancel(self) -> bool:
        r=self._run(['shutdown.exe','/a'])
        if r.returncode not in (0,1116):raise OSError('shutdown_cancel_failed')
        return r.returncode==0
    # ------------------------------------------------------------ protocol steps
    def launch(self, target: str) -> None:
        """Open a configured workspace entry: a URL, an existing file or folder, else a command line."""
        target=os.path.expandvars(target.strip())
        if not target:raise ValueError('empty_target')
        uri=re.match(r'^[a-z][a-z0-9+.-]+:',target,re.I) is not None  # https:, spotify:, ... but not C:\
        if uri or os.path.exists(target):_WIN_OS.startfile(target);return
        subprocess.Popen(target,shell=False,creationflags=CREATE_NEW_CONSOLE if os.name=='nt' else 0)  # «cmd.exe» gets its window
    def work_area(self) -> tuple[int, int, int, int]:
        """Primary monitor work area (x, y, w, h), excluding the taskbar (SPI_GETWORKAREA)."""
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        r = RECT(); u = _WIN.windll.user32
        u.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        if u.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
            return int(r.l), int(r.t), int(r.r - r.l), int(r.b - r.t)
        w, h = self.screen_size(); return 0, 0, w, h
    def open_window(self, target: str, place: str | None = None, title: str | None = None) -> int:
        """Start a program or .bat/.cmd in a new window of the system's default terminal
        (Windows Terminal when it is the default, otherwise the classic console) and return
        its process id, so «отмена протокола» can close it. ``place`` is a named half of the
        primary work area (``left_half`` / ``right_half``), applied with SetWindowPos."""
        from jarvis.core.protocols import placed_rect
        target = os.path.expandvars(target.strip())
        if not target: raise ValueError("empty_target")
        title = re.sub(r"[^\w -]", "", title or "")[:40] or ("jarvis-" + uuid.uuid4().hex[:8])
        before = self._terminal_hwnds()
        pid = self._start_terminal(target, title)
        hwnd = self._wait_new_terminal(before, title)
        if hwnd and place:
            rect = placed_rect(self.work_area(), place)
            if rect: self._set_window_rect(hwnd, rect)
        if hwnd: self._protocol_hwnds()[int(pid)] = hwnd
        return int(pid)
    def _protocol_hwnds(self) -> dict[int, int]:
        store = getattr(self, "_protocol_hwnd_map", None)
        if store is None:
            store = {}; self._protocol_hwnd_map = store
        return store
    def _start_terminal(self, target: str, title: str) -> int:
        cwd = os.path.dirname(target) or None
        wt = _wt_exe() if _windows_terminal_is_default() else None
        if wt:
            # Force a new window, never a tab on an already open Terminal session.
            args = [wt, "--window", "new", "--title", title, "--suppressApplicationTitle", "--", "cmd.exe", "/c", target]
            return int(subprocess.Popen(args, shell=False, cwd=cwd).pid)
        flags = CREATE_NEW_CONSOLE if os.name == "nt" else 0
        args = ["cmd.exe", "/c", "title " + title + " & " + target]
        return int(subprocess.Popen(args, shell=False, cwd=cwd, creationflags=flags).pid)
    def _terminal_hwnds(self) -> set[int]:
        return {h for h, _cls, _title in self._enum_terminals()}
    def _enum_terminals(self) -> list[tuple[int, str, str]]:
        """Visible top-level terminal windows as (hwnd, class name, title)."""
        u = _WIN.windll.user32; out: list[tuple[int, str, str]] = []
        u.IsWindowVisible.argtypes = [ctypes.c_void_p]
        u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        u.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        u.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        proto = _WIN.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def visit(h: Any, _: Any) -> bool:
            if not u.IsWindowVisible(h): return True
            cls = ctypes.create_unicode_buffer(256); u.GetClassNameW(h, cls, 256)
            if cls.value not in TERMINAL_WINDOW_CLASSES: return True
            n = u.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, buf, n + 1)
            out.append((int(h), cls.value, buf.value)); return True
        u.EnumWindows(proto(visit), None); return out
    def _wait_new_terminal(self, before: set[int], title: str, timeout_s: float = 5.0) -> int | None:
        needle = title.casefold(); deadline = time.time() + timeout_s; last: list[int] = []
        while time.time() < deadline:
            found = [(h, text) for h, _cls, text in self._enum_terminals() if h not in before]
            last = [h for h, _t in found]
            named = [h for h, text in found if needle and needle in text.casefold()]
            if named: return named[0]
            if len(found) == 1 and time.time() + 0.4 >= deadline: return found[0][0]
            time.sleep(0.1)
        return last[0] if len(last) == 1 else None
    def _set_window_rect(self, hwnd: int, rect: tuple[int, int, int, int]) -> None:
        u = _WIN.windll.user32
        u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u.SetWindowPos(hwnd, None, rect[0], rect[1], rect[2], rect[3], 0x0004 | 0x0040)  # SWP_NOZORDER | SWP_SHOWWINDOW
    def _windows(self) -> list[tuple[int, int, str]]:
        """Visible, titled, uncloaked top-level user windows as (hwnd, pid, process name without .exe, lower case)."""
        u=_WIN.windll.user32;k=_WIN.windll.kernel32;out: list[tuple[int, int, str]] = []
        dwm=_WIN.WinDLL('dwmapi');dwm.DwmGetWindowAttribute.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint]
        u.GetWindowTextLengthW.argtypes=[ctypes.c_void_p];u.GetWindowLongW.argtypes=[ctypes.c_void_p,ctypes.c_int]
        proto=_WIN.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
        u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];u.IsWindowVisible.argtypes=[ctypes.c_void_p]
        u.GetWindow.argtypes=[ctypes.c_void_p,ctypes.c_uint];u.GetWindow.restype=ctypes.c_void_p
        k.OpenProcess.restype=ctypes.c_void_p;k.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
        k.CloseHandle.argtypes=[ctypes.c_void_p]
        def visit(h: Any, _: Any) -> bool:
            if not u.IsWindowVisible(h) or u.GetWindow(h,4):return True  # GW_OWNER: skip dialogs owned by another window
            if not u.GetWindowTextLengthW(h) or u.GetWindowLongW(h,-20)&0x80:return True  # untitled or WS_EX_TOOLWINDOW
            cloaked=ctypes.c_int(0);dwm.DwmGetWindowAttribute(h,14,ctypes.byref(cloaked),4)  # DWMWA_CLOAKED: hidden UWP frames
            if cloaked.value:return True
            pid=ctypes.c_ulong();u.GetWindowThreadProcessId(h,ctypes.byref(pid));name=''
            hp=k.OpenProcess(0x1000,False,pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if hp:
                buf=ctypes.create_unicode_buffer(520);size=ctypes.c_ulong(520)
                if k.QueryFullProcessImageNameW(hp,0,buf,ctypes.byref(size)):name=Path(buf.value).stem.lower()
                k.CloseHandle(hp)
            out.append((int(h),int(pid.value),name));return True
        u.EnumWindows(proto(visit),None);return out
    def close_apps(self, names: list[str], protect: set[int]) -> int:
        """Ask the windows of the listed processes to close (WM_CLOSE, like the × button); never kills.
        An app that asks «save?» stays open. Jarvis, its terminal and the shell are never touched."""
        wanted={Path(n.strip().lower()).stem for n in names if n.strip()}-PROTECTED_PROCESSES;count=0
        if not wanted:return 0
        u=_WIN.windll.user32;u.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
        for h,pid,name in self._windows():
            if name in wanted and pid not in protect and u.PostMessageW(h,0x10,0,0):count+=1
        return count
    def close_windows(self, protect: set[int]) -> int:
        """Ask every open user window to close (WM_CLOSE, like the × button); never kills. Jarvis
        (``protect`` pids and Python), Explorer and system UI hosts stay; unsaved work keeps its window."""
        u=_WIN.windll.user32;u.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t];count=0
        for h,pid,name in self._windows():
            if name and name not in SHELL_PROCESSES and pid not in protect and u.PostMessageW(h,0x10,0,0):count+=1
        return count
    def minimize_all(self) -> None:
        u=_WIN.windll.user32;u.FindWindowW.restype=ctypes.c_void_p;u.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p]
        tray=u.FindWindowW('Shell_TrayWnd',None)
        if not tray:raise OSError('taskbar_not_found')
        u.SendMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t];u.SendMessageW(tray,0x111,419,0)  # WM_COMMAND MIN_ALL
    def screen_size(self) -> tuple[int, int]:
        u=_WIN.windll.user32;return int(u.GetSystemMetrics(0)),int(u.GetSystemMetrics(1))
    def open_console(self, command: str, title: str, rect: tuple[int, int, int, int], cwd: str | None = None) -> int:
        """A classic console window with green text running ``command`` (the caller passes only
        whitelisted commands), moved to ``rect``; returns the process id to close it later."""
        title=re.sub(r'[^\w -]','',title)[:40] or 'jarvis'
        p=subprocess.Popen(['conhost.exe','cmd.exe','/k','title '+title+' & color 0a & '+command],cwd=cwd,creationflags=CREATE_NEW_CONSOLE)
        u=_WIN.windll.user32;u.FindWindowW.restype=ctypes.c_void_p;u.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p]
        u.MoveWindow.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_bool]
        for _ in range(30):  # the console sets its title a moment after start
            h=u.FindWindowW('ConsoleWindowClass',title)
            if h:u.MoveWindow(h,*rect,True);break
            time.sleep(.1)
        return int(p.pid)
    def end_process(self, pid: int) -> None:
        """Close a window this backend opened. For a snapped Windows Terminal window, send
        WM_CLOSE to that window only (never kill the shared WindowsTerminal process). Then
        taskkill the process tree as a fallback (cmd and its ssh). 128 means already gone."""
        hwnd = self._protocol_hwnds().pop(int(pid), None)
        if hwnd:
            u = _WIN.windll.user32
            u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
            u.IsWindow.argtypes = [ctypes.c_void_p]; u.PostMessageW(hwnd, 0x10, 0, 0)  # WM_CLOSE
            for _ in range(20):
                if not u.IsWindow(hwnd): break
                time.sleep(0.1)
        r = self._run(["taskkill.exe", "/PID", str(int(pid)), "/T", "/F"])
        if r.returncode not in (0, 128):
            if hwnd and not _WIN.windll.user32.IsWindow(hwnd): return
            raise OSError("taskkill_failed")
    def playlist(self, url: str) -> None:
        if not re.match(r'^https?://',url):raise ValueError('invalid_playlist_url')
        _WIN_OS.startfile(url)
    def git(self, project: str, which: str, projects_dir: str | None = None) -> str:
        if not project:raise ValueError('name_project')
        path,score=LAPTOP.find_project(project,JT.latin,projects_dir)
        if not path or score<.5:raise ValueError('project_not_found')
        args=['git','--no-optional-locks','-C',path]
        if which=='last':
            r=self._run(args+['log','-1','--format=%h %s'])
            if r.returncode:raise ValueError('git_unavailable')
            return 'Последний коммит проекта '+Path(path).name+': '+r.stdout.strip()[:350]+'.'
        r=self._run(args+['status','--porcelain=1','--branch'])
        if r.returncode:raise ValueError('git_unavailable')
        lines=r.stdout.splitlines();branch=lines[0][3:] if lines and lines[0].startswith('## ') else 'неизвестна';changed=sum(not x.startswith('## ') for x in lines)
        return 'Проект '+Path(path).name+'. Ветка '+branch+'. '+('Незакоммиченных изменений нет.' if not changed else 'Изменённых или новых файлов: '+str(changed)+'.')
