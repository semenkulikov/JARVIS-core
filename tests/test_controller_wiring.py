"""The composition root wires real adapters into the controller; tests only swap ports."""
from jarvis.adapters.project_tools import ProjectTools
from jarvis.adapters.system import SystemBackend
from jarvis.adapters.timers import PersistentTimers
from jarvis.app.context import build_controller
from jarvis.commands.controller import Controller


def test_build_controller_uses_real_adapters_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_SCREENSHOTS", raising=False)
    c = build_controller(tmp_path)
    assert isinstance(c, Controller) and isinstance(c.backend, SystemBackend) and isinstance(c.timers, PersistentTimers)
    assert isinstance(c.tools, ProjectTools) and c.screenshots == tmp_path / "screenshots"


def test_git_gets_the_configured_projects_folder(tmp_path, cfg):
    calls = []

    class Backend:
        is_fake = True
        def git(self, project, which, projects_dir=None): calls.append((project, which, projects_dir)); return "ok"
    c = build_controller(tmp_path, Backend())
    said = []
    c.execute({"cmd": "git", "project": "demo", "which": "status"}, "", dict(cfg, projects_dir="D:/code"),
              lambda text, cfg, **kw: said.append(text) or True, lambda *a, **k: None)
    assert calls == [("demo", "status", "D:/code")] and said == ["ok"]


def test_food_logger_reads_fatsecret_per_call(tmp_path, cfg):
    seen = []
    c = build_controller(tmp_path, food_call=lambda method, params: seen.append(method) or {"food_entries": None})
    assert "белка" in c.food(dict(cfg, nutrition_targets={})).remaining() and seen == ["food_entries.get"]
