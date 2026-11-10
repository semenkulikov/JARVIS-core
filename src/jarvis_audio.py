"""Single-owner audio output.

PortAudio streams are not thread-safe: calling ``sounddevice.stop()`` from the main loop
while the speech thread sits in ``sounddevice.wait()`` frees the stream under the other
thread (access violation in ntdll, seen 2026-11-10 11:29 after a priority wake). Here only
the thread that started playback ever touches the stream; other threads ask it to stop.
"""
import threading
import time
from typing import Any, Callable

import numpy as np


class Player:
    def __init__(self, sd: Any, poll_s: float = 0.02):
        self.sd = sd
        self.poll_s = poll_s
        self._lock = threading.Lock()

    def play(self, buf: np.ndarray, sr: int, should_stop: Callable[[], bool] = lambda: False) -> bool:
        """Play ``buf`` and block; returns False when ``should_stop`` ended it early."""
        with self._lock:
            if should_stop():
                return False
            self.sd.play(buf, sr)
            get_stream = getattr(self.sd, "get_stream", None)
            if get_stream is None:  # minimal backends (tests): no polling possible
                self.sd.wait()
                return True
            deadline = time.monotonic() + len(buf) / float(sr) + 1.0
            finished = True
            try:
                while time.monotonic() < deadline:
                    if should_stop():
                        finished = False
                        break
                    try:
                        if not get_stream().active:
                            break
                    except RuntimeError:
                        break
                    time.sleep(self.poll_s)
            finally:
                self.sd.stop()  # same thread that started the stream
            return finished

    def idle(self, timeout: float = 1.0) -> bool:
        """Wait until no playback is running (used before process exit)."""
        if self._lock.acquire(timeout=timeout):
            self._lock.release()
            return True
        return False
