import threading

from jarvis.core.lazy import Lazy


def test_created_once_on_first_get():
    made = []
    lz = Lazy(lambda: made.append(1) or object())
    assert lz.peek() is None and made == []
    v = lz.get()
    assert lz.get() is v and lz.peek() is v and made == [1]


def test_concurrent_first_use_creates_one_value():
    made = []
    gate = threading.Barrier(8)
    lz = Lazy(lambda: made.append(1) or object())
    def use(): gate.wait(); lz.get()
    ts = [threading.Thread(target=use) for _ in range(8)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert made == [1]


def test_set_replaces_the_value():
    lz = Lazy(lambda: "real")
    lz.set("fake")
    assert lz.get() == "fake"
