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
