"""Locations from the environment (no system actions)."""

import pytest

from jarvis.adapters import paths as P


def test_log_dir_default_and_env(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_LOG_DIR", raising=False)
    assert P.log_dir() == P.HOME / "logs"
    monkeypatch.setenv("JARVIS_LOG_DIR", str(tmp_path / "logs" / "voice"))
    assert P.log_dir() == tmp_path / "logs" / "voice"


def test_screenshots_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_SCREENSHOTS", raising=False)
    assert P.screenshots_dir(tmp_path) == tmp_path / "screenshots"
    monkeypatch.setenv("JARVIS_SCREENSHOTS", str(tmp_path / "shots"))
    assert P.screenshots_dir(tmp_path) == tmp_path / "shots"


@pytest.mark.parametrize("value,expected", [
    ("", P.DEFAULT_CREDENTIAL_PREFIX),
    ("Sem.Jarvis.", "Sem.Jarvis."),
    ("no-dot", P.DEFAULT_CREDENTIAL_PREFIX),
    ("bad prefix.", P.DEFAULT_CREDENTIAL_PREFIX),
])
def test_credential_prefix(monkeypatch, value, expected):
    monkeypatch.setenv("JARVIS_CREDENTIAL_PREFIX", value)
    assert P.credential_prefix() == expected


def test_credentials_use_prefix(monkeypatch):
    from jarvis.adapters import credentials as C
    monkeypatch.setenv("JARVIS_CREDENTIAL_PREFIX", "Sem.Jarvis.")
    assert C.service("webhook_auth_header") == "Sem.Jarvis.webhook_auth_header"
    with pytest.raises(ValueError):
        C.service("anything_else")
