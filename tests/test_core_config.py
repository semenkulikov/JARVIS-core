import json

from jarvis.core.config import ConfigIssue, ConfigStore, validate


def _store(tmp_path, data, finalize=lambda cfg: None):
    (tmp_path / "config.json").write_text(json.dumps(data), encoding="utf-8")
    return ConfigStore(str(tmp_path / "config.json"), {"a": 1.0, "flag": True, "acks": ["x"], "name": ""}, finalize, migrate=lambda c, d: [])


def test_store_overlays_defaults_and_caches_until_the_file_changes(tmp_path):
    seen = []
    store = _store(tmp_path, {"a": 2}, finalize=lambda cfg: seen.append(dict(cfg)))
    first = store.load()
    assert first["a"] == 2 and first["flag"] is True and store.load() is first and len(seen) == 1


def test_broken_file_keeps_the_last_good_config(tmp_path):
    store = _store(tmp_path, {"a": 3})
    good = store.load()
    p = tmp_path / "config.json"; p.write_text("{broken", encoding="utf-8")
    import os
    os.utime(p, (1, 1))
    assert store.load() is good


def test_validate_reports_type_mismatches_only():
    defaults = {"a": 1.0, "flag": True, "acks": ["x"], "name": "", "free": None}
    cfg = {"a": 2, "flag": "yes", "acks": "один", "name": ["list ok"], "free": 5, "own": {}}
    assert validate(cfg, defaults) == [ConfigIssue("flag", "bool", "text or list")]
    assert str(validate({"a": True}, defaults)[0]) == "a: expected number, got bool"
