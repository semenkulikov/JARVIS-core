import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import eval_calibration as E  # noqa: E402


def test_route_key_ignores_transcript_specific_fields():
    a = {"name": "today", "action": "cache_field", "field": "today", "_fuzzy_score": 95.2, "phrases": ["какие планы"]}
    b = {"name": "today", "action": "cache_field", "field": "today", "_fuzzy_score": 100.0}
    assert E.route_key(a) == E.route_key(b) and E.route_key(None) is None
    assert E.route_key({"action": "webhook", "target": "x"}) == E.route_key({"action": "webhook", "target": "y"})


def test_reference_text_and_overrides():
    assert E.reference_text({"text": "Джарвис … что ты умеешь"}) == "что ты умеешь"
    assert E.reference_text({"text": "который час"}) == "который час"
    assert E.parse_overrides(["wake_verify_normalize=false", "speaker_threshold=0.4", "speaker_profile=a/b.json"]) == {
        "wake_verify_normalize": False, "speaker_threshold": 0.4, "speaker_profile": "a/b.json"}


def test_background_helpers_pick_the_calm_part():
    room = np.concatenate([np.full(16000, 0.3), np.full(16000, 0.001), np.full(16000, 0.2)]).astype(np.float32)
    assert float(np.abs(E.quiet_background(room, 1.0)).max()) < 0.01
    assert len(E.quiet_background(None, 0.5)) == 8000
    assert len(E.background_windows(room, 2.0, hop=0.5)) == 3 and E.background_windows(None, 2.0) == []


def test_threshold_sits_between_owner_and_background():
    owner = [0.42, 0.45, 0.5, 0.55, 0.6, 0.62, 0.18, 0.52, 0.58, 0.61]
    t = E.suggest_speaker_threshold(owner, [0.0, 0.2, 0.376])
    assert t is not None and 0.376 < t["threshold"] < 0.42 and t["margin_background"] > 0 and t["owner_rejected"] == 1
    assert E.suggest_speaker_threshold([], [0.1]) is None


def test_summary_counts_wakes_commands_and_rejections():
    rows = [
        {"kind": "wake", "file": "1", "wake": {"candidate": True, "triggered": True, "verify": True, "speaker_ok": True, "speaker_score": 0.5}},
        {"kind": "wake", "file": "2", "wake": {"candidate": True, "triggered": False, "verify": False, "speaker_ok": None}},
        {"kind": "wake_command", "file": "3", "peak": 0.2, "wake": {"candidate": True, "triggered": False, "verify": True, "speaker_ok": False},
         "command": {"correct": False}},
        {"kind": "command", "file": "4", "peak": 0.1, "speaker": 0.4, "command": {"correct": True}},
        {"kind": "command", "file": "5", "peak": 0.01, "command": {"correct": False}},
    ]
    s = E.summarize(rows, [0.1])
    assert (s["wake_triggered"], s["wake_total"], s["verify_rejected"], s["speaker_rejected"]) == (1, 3, 1, 1)
    assert (s["commands_correct"], s["commands_total"]) == (1, 3)
    assert E.training_clips(rows) == ["3"]  # every other clearly spoken command clip
