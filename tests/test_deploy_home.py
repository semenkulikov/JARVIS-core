"""Home launcher rendering and installation (never starts anything)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import deploy_home as D  # noqa: E402


def test_render_launcher_sets_env(tmp_path):
    text = D.render_launcher(tmp_path, Path(r"C:\v\pythonw.exe"), {"JARVIS_LOG_DIR": r'C:\l "x"'}, repo=Path(r"C:\repo"))
    assert 'pe("JARVIS_HOME") = "%s"' % tmp_path in text
    assert 'pe("JARVIS_LOG_DIR") = "C:\\l ""x"""' in text
    assert r'C:\repo\src\jarvis_supervisor.py' in text and "\r\n" in text


def test_parse_env_allowlist():
    assert D.parse_env(["JARVIS_LOG_DIR=C:\\x"]) == {"JARVIS_LOG_DIR": "C:\\x"}
    with pytest.raises(SystemExit):
        D.parse_env(["PATH=C:\\evil"])


def test_install_launcher_keeps_first_backup(tmp_path):
    (tmp_path / D.LAUNCHER).write_text("old", encoding="utf-8")
    backup = D.install_launcher(tmp_path, "new1")
    D.install_launcher(tmp_path, "new2")
    assert backup.read_text(encoding="utf-8") == "old"
    assert (tmp_path / D.LAUNCHER).read_text(encoding="utf-8") == "new2"
