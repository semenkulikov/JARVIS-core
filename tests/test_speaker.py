"""Speaker verification: frontend, scoring, profile and fail-open behaviour (no model)."""
import json

import numpy as np
import pytest

import jarvis_speaker as S
from jarvis.adapters.speaker import SpeakerGate


def tone(hz, seconds=1.0, sr=16000):
    t = np.arange(int(seconds * sr)) / sr
    return (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_fbank_shape_and_cmn():
    f = S.fbank(tone(440))
    assert f.shape == (98, 80) and f.dtype == np.float32
    assert np.allclose(f.mean(axis=0), 0, atol=1e-3)


def test_fbank_short_clip():
    assert S.fbank(np.zeros(100, np.float32)).shape == (0, 80)


def test_fbank_peak_follows_pitch():
    low = S.fbank(np.concatenate([tone(300), np.zeros(16000, np.float32)]))
    high = S.fbank(np.concatenate([tone(3000), np.zeros(16000, np.float32)]))
    assert int(np.argmax(low[:50].mean(axis=0))) < int(np.argmax(high[:50].mean(axis=0)))


def test_trim_silence():
    a = np.concatenate([np.zeros(8000), tone(300, 0.5), np.zeros(8000)]).astype(np.float32)
    t = S.trim_silence(a)
    assert 7000 <= len(t) <= 8640 and S.trim_silence(np.zeros(4000, np.float32)).size == 0


def test_cosine_and_centroid():
    a, b = np.array([1.0, 0.0]), np.array([0.0, 2.0])
    assert S.cosine(a, a) == pytest.approx(1.0) and S.cosine(a, b) == pytest.approx(0.0)
    assert S.cosine(a, np.zeros(2)) == 0.0
    assert np.allclose(S.centroid([a, b * 0.5]), [0.5, 0.5])


def test_threshold_from_consistent_owner_is_high_but_clamped():
    rng = np.random.default_rng(1)
    base = rng.normal(size=256)
    owner = [base + 0.05 * rng.normal(size=256) for _ in range(6)]
    assert S.suggest_threshold(owner) == 0.6


def test_threshold_lower_bound():
    rng = np.random.default_rng(2)
    assert S.suggest_threshold([rng.normal(size=256) for _ in range(5)]) == 0.35
    assert S.suggest_threshold([np.ones(3)]) == 0.5


class FakeSession:
    def __init__(self, vec):
        self.vec = np.asarray(vec, dtype=np.float32)
        self.seen = []

    def get_inputs(self):
        return [type("I", (), {"name": "feats"})()]

    def run(self, _, feeds):
        self.seen.append(feeds["feats"].shape)
        return [self.vec[None, :]]


def make_home(tmp_path, centroid, threshold=0.6):
    (tmp_path / "speaker").mkdir()
    (tmp_path / "speaker" / "profile.json").write_text(json.dumps({"version": 1, "centroid": centroid, "threshold": threshold}), encoding="utf-8")
    return tmp_path


def test_disabled_by_default_never_loads(tmp_path):
    v = S.SpeakerVerifier(tmp_path, {}, session_factory=lambda p: pytest.fail("must not load"))
    assert v.check(tone(300, 2)) == (True, None)


def test_accepts_owner_and_rejects_stranger(tmp_path):
    home = make_home(tmp_path, [1.0, 0.0, 0.0])
    owner = S.SpeakerVerifier(home, {"speaker_verify_enabled": True}, session_factory=lambda p: FakeSession([0.9, 0.1, 0.0]))
    ok, score = owner.check(tone(300, 2))
    assert ok and score > 0.9
    stranger = S.SpeakerVerifier(home, {"speaker_verify_enabled": True}, session_factory=lambda p: FakeSession([0.1, 1.0, 0.0]))
    ok, score = stranger.check(tone(300, 2))
    assert not ok and score < 0.6


def test_config_threshold_overrides_profile(tmp_path):
    home = make_home(tmp_path, [1.0, 0.0], threshold=0.99)
    v = S.SpeakerVerifier(home, {"speaker_verify_enabled": True, "speaker_threshold": 0.5}, session_factory=lambda p: FakeSession([0.8, 0.6]))
    assert v.check(tone(300, 2))[0] is True and v.threshold() == 0.5


def test_short_audio_is_not_judged(tmp_path):
    home = make_home(tmp_path, [1.0, 0.0])
    v = S.SpeakerVerifier(home, {"speaker_verify_enabled": True}, session_factory=lambda p: FakeSession([0.0, 1.0]))
    assert v.check(tone(300, 0.3)) == (True, None)


def test_missing_profile_fails_open(tmp_path):
    v = S.SpeakerVerifier(tmp_path, {"speaker_verify_enabled": True}, session_factory=lambda p: FakeSession([1.0]))
    assert v.check(tone(300, 2)) == (True, None) and v.error


def test_make_profile_roundtrip():
    p = S.make_profile([np.array([1.0, 0.0]), np.array([0.9, 0.1]), np.array([1.0, 0.1])])
    assert p["version"] == 1 and p["count"] == 3 and p["model_sha256"] == S.MODEL_SHA256 and len(p["centroid"]) == 2


def test_listener_gate_off_by_default(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(S, "SpeakerVerifier", lambda *a, **k: pytest.fail("must not construct"))
    assert SpeakerGate(str(tmp_path)).ok([], 16000, cfg) is True


def test_listener_gate_rejects_stranger(cfg, tmp_path):
    home = make_home(tmp_path, [1.0, 0.0])
    cfg["speaker_verify_enabled"] = True
    gate = SpeakerGate(str(home))
    gate.verifier = S.SpeakerVerifier(home, cfg, session_factory=lambda p: FakeSession([0.0, 1.0]))
    ring = [(0, tone(300, 2.0))]
    assert gate.ok(ring, 32000, cfg) is False and gate.owner_confirmed(ring, 32000, cfg) is False


def test_owner_confirmed_needs_real_score(cfg, tmp_path):
    assert SpeakerGate(str(tmp_path)).owner_confirmed([], 0, dict(cfg, speaker_verify_enabled=False)) is False
