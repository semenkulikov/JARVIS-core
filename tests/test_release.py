import re
from pathlib import Path

import jarvis

ROOT = Path(__file__).resolve().parent.parent


def test_versions_agree():
    project = re.search(r'^version = "([\d.]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    latest = re.search(r"^## \[([\d.]+)\]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M).group(1)
    assert jarvis.__version__ == project == latest


def test_every_changelog_version_has_a_compare_link():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^## \[([\d.]+)\]", text, re.M)
    links = dict(re.findall(r"^\[([\d.]+)\]: (\S+)$", text, re.M))
    assert set(links) == set(versions)
    for newer, older in zip(versions, versions[1:], strict=False):
        assert links[newer].endswith(f"/compare/v{older}...v{newer}")
    assert links[versions[-1]].endswith(f"/releases/tag/v{versions[-1]}")
