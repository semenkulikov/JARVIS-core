import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import calibrate_voice as C  # noqa: E402


def test_plan_covers_wake_commands_pairs_and_silence_within_budget():
    plan = C.build_plan()
    kinds = [i.kind for i in plan]
    assert kinds.count("wake") == 10 and kinds.count("wake_command") == 10 and kinds.count("silence") == 1
    commands = [i.text for i in plan if i.kind == "command"]
    assert len(commands) == C.MAX_COMMANDS == len(set(commands))
    assert set(C.PRIORITY) <= set(commands)
    assert sum(i.seconds for i in plan) <= 5 * 60
    assert len({C.slug(item, n) for n, item in enumerate(plan, 1)}) == len(plan)


def test_run_records_skips_redoes_and_quits(tmp_path):
    plan = [C.Item("wake", "Джарвис", "h", 0.1), C.Item("command", "который час", "h", 0.1), C.Item("silence", "", "h", 0.1)]
    keys = iter(["", "r", "", "", "s"])
    takes = iter([0.02, 0.5, 0.3])
    rows = C.run(plan, tmp_path, lambda s: np.full(int(s * 16000), next(takes), dtype=np.float32),
                 ask=lambda prompt: next(keys), say=lambda line: None)
    assert [r["kind"] for r in rows] == ["wake", "command"]
    assert rows[0]["peak"] == 0.5  # the redo replaced the quiet first take
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sample_rate"] == 16000 and [c["file"] for c in manifest["clips"]] == [r["file"] for r in rows]
    with wave.open(str(tmp_path / rows[1]["file"]), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 1600)


def test_quit_keeps_what_was_recorded(tmp_path):
    plan = [C.Item("wake", "Джарвис", "h", 0.1)] * 3
    keys = iter(["", "q"])
    rows = C.run(plan, tmp_path, lambda s: np.zeros(1600, dtype=np.float32), ask=lambda p: next(keys), say=lambda line: None)
    assert len(rows) == 1 and (tmp_path / rows[0]["file"]).exists()
    assert C.level_note(0.01) and C.level_note(0.3) == ""
