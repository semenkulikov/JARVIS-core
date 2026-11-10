import os
import time

from jarvis.adapters.outbox import Outbox
from jarvis.core.state import RequestLedger


class _Sig:
    def clear(self): pass
    def wait(self, cfg): pass


def test_paths_read_and_move(tmp_path):
    box = Outbox(str(tmp_path), signal=_Sig()); box.ensure()
    p = box.part("r1", 2)
    with open(p, "w", encoding="utf-8") as f: f.write("\ufeffЧасть.")
    assert p.endswith("r1.2.txt") and box.final("r1").endswith("r1.txt")
    assert box.read(p) == "Часть." and box.ready(p)
    box.move_done(p)
    assert not os.path.exists(p) and os.path.exists(os.path.join(box.done, "r1.2.txt"))


def test_empty_file_is_not_ready_unless_allowed(tmp_path):
    p = tmp_path / "r.txt"; p.write_text("", encoding="utf-8")
    assert not Outbox.ready(str(p)) and Outbox.ready(str(p), allow_empty=True)


def test_purge_drops_late_parts_and_forgets_old_requests(tmp_path):
    box = Outbox(str(tmp_path), signal=_Sig()); led = RequestLedger()
    led.cancel("late"); led.cancelled["old"] = time.time() - 1000
    (tmp_path / "late.1.txt").write_text("x", encoding="utf-8"); (tmp_path / "keep.txt").write_text("y", encoding="utf-8")
    box.purge_cancelled(led)
    assert sorted(os.listdir(tmp_path)) == ["keep.txt"] and list(led.cancelled) == ["late"]
