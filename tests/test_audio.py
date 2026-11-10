"""Audio stream ownership: only the playing thread touches PortAudio (crash fix)."""
import threading
import time

import numpy as np

from jarvis.adapters import playback as A


class FakeStream:
    def __init__(self, seconds):
        self.until = time.monotonic() + seconds

    @property
    def active(self):
        return time.monotonic() < self.until


class FakeSD:
    def __init__(self, seconds=0.3):
        self.seconds = seconds
        self.calls = []
        self.stream = None

    def play(self, buf, sr):
        self.calls.append(("play", threading.get_ident()))
        self.stream = FakeStream(self.seconds)

    def get_stream(self):
        if self.stream is None:
            raise RuntimeError("no stream")
        return self.stream

    def stop(self):
        self.calls.append(("stop", threading.get_ident()))
        self.stream = None


def test_plays_to_end():
    sd = FakeSD(0.05)
    assert A.Player(sd, poll_s=0.005).play(np.zeros(800, np.float32), 16000) is True
    assert [c[0] for c in sd.calls] == ["play", "stop"]


def test_stop_request_from_other_thread_never_touches_stream():
    sd = FakeSD(5.0)
    player = A.Player(sd, poll_s=0.005)
    flag = threading.Event()
    result = []
    t = threading.Thread(target=lambda: result.append(player.play(np.zeros(16000 * 5, np.float32), 16000, flag.is_set)))
    t.start()
    time.sleep(0.05)
    main_thread = threading.get_ident()
    flag.set()  # what the main loop does on barge-in / priority wake
    t.join(1.0)
    assert result == [False]
    assert all(ident != main_thread for _, ident in sd.calls)
    assert {ident for _, ident in sd.calls} == {t.ident}


def test_already_interrupted_does_not_play():
    sd = FakeSD()
    assert A.Player(sd).play(np.zeros(10, np.float32), 16000, lambda: True) is False and sd.calls == []


def test_backend_without_get_stream_uses_wait():
    calls = []

    class Minimal:
        def play(self, buf, sr): calls.append("play")
        def wait(self): calls.append("wait")

    assert A.Player(Minimal()).play(np.zeros(10, np.float32), 16000) is True and calls == ["play", "wait"]


def test_idle_waits_for_playback():
    sd = FakeSD(0.2)
    player = A.Player(sd, poll_s=0.005)
    t = threading.Thread(target=lambda: player.play(np.zeros(3200, np.float32), 16000))
    t.start()
    time.sleep(0.02)
    assert player.idle(0.01) is False
    assert player.idle(1.0) is True
    t.join()


def test_listener_has_no_cross_thread_stop():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "src"
    # Only the playback adapter owns the stream; everything else asks it to stop.
    files = [root / "jarvis_voice.py", *sorted(p for p in (root / "jarvis").rglob("*.py") if p.name != "playback.py")]
    src = "".join(f.read_text(encoding="utf-8") for f in files)
    assert len(files) > 5 and "sd.stop()" not in src and "sd.wait()" not in src
