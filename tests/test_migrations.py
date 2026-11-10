"""Versioned config migrations and config-driven pronunciations."""
import json
from pathlib import Path

import jarvis_migrations as M
import jarvis_text as JT

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {"ack_stop": ["Как скажете, сэр."]}


def test_legacy_config_gets_listener_tuning():
    cfg = {"phrase_silence_s": 1.0, "bargein_min_conf": 0.7, "ack_stop": ["old"]}
    assert M.migrate(cfg, DEFAULTS) == [1]
    assert cfg == {"phrase_silence_s": 0.95, "bargein_min_conf": 0.60, "ack_stop": DEFAULTS["ack_stop"], "config_version": M.CURRENT}


def test_current_config_untouched():
    cfg = {"config_version": M.CURRENT, "phrase_silence_s": 1.2}
    assert M.migrate(cfg, DEFAULTS) == [] and cfg["phrase_silence_s"] == 1.2


def test_garbage_version_is_legacy():
    cfg = {"config_version": "x"}
    assert M.migrate(cfg, DEFAULTS) == [1]


def test_example_config_is_current():
    assert json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))["config_version"] == M.CURRENT


def test_listener_applies_migrations(monkeypatch, tmp_path):
    import jarvis_credentials as CREDS
    from jarvis.app import settings
    (tmp_path / "config.json").write_text('{"phrase_silence_s": 1.0}', encoding="utf-8")
    monkeypatch.setattr(CREDS, "webhook", lambda cfg, base: "")
    cfg = settings.config_store(tmp_path).load()
    assert cfg["phrase_silence_s"] == 0.95 and cfg["config_version"] == M.CURRENT


def test_extend_latin():
    JT.extend_latin({"Mercusys": "меркусис", "": "x", "bad": 3})
    assert JT.LATIN["mercusys"] == "меркусис" and "" not in JT.LATIN and "bad" not in JT.LATIN
