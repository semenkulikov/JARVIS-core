import datetime
import json

from jarvis.adapters.status_cache import StatusCache


def _write(tmp_path, data):
    p = tmp_path / "status.json"; p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return StatusCache(str(p))


def test_missing_file_is_missing_not_an_error(tmp_path, cfg):
    c = StatusCache(str(tmp_path / "none.json"))
    assert c.cached_status(None, cfg) == ("missing", "", None) and c.load() is None and c.github_url() is None
    assert c.tasks_snapshot(cfg) == (None, False, "")


def test_github_url_from_projects(tmp_path):
    assert _write(tmp_path, {"projects": [{"repo": "owner/name/"}]}).github_url() == "https://github.com/owner/name"
    assert _write(tmp_path, {"projects": "https://example.invalid/r"}).github_url() == "https://example.invalid/r"


def test_tasks_snapshot_is_fresh_with_a_stamp(tmp_path, cfg):
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    data, fresh, stamp = _write(tmp_path, {"updated": now}).tasks_snapshot(cfg)
    assert data == {"updated": now} and fresh and stamp.startswith("Данные на ")
