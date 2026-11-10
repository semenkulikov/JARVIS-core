import re
import sys
from pathlib import Path

import pytest

import jarvis_registry as R
from jarvis.app import settings as SETTINGS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gen_commands_doc as G  # noqa: E402

EXAMPLES = [(c.id, e) for c in R.COMMANDS for e in c.examples]


@pytest.mark.parametrize("cid,example", EXAMPLES)
def test_every_example_routes_to_its_command(listener, cfg, cid, example):
    cfg["food_local_enabled"] = True
    assert R.route_id(listener.match_alias(example, cfg)) == cid


def test_every_default_alias_is_registered():
    for al in SETTINGS.DEFAULT_ALIASES:
        # a quick command with the same name handles those phrases first
        assert al["name"] in R.BY_ID or "q:" + al["name"] in R.BY_ID, al["name"]


def test_every_quick_command_is_registered():
    src = "".join((ROOT / "src" / f).read_text(encoding="utf-8") for f in ("jarvis_commands.py",))
    for cmd in set(re.findall(r"a\('([a-z_]+)'", src)) | {"explain_error", "confirm_in_chat", "server_health", "project_tests", "nutrition_left"}:
        assert "q:" + cmd in R.BY_ID, cmd


def test_ids_unique_and_categories_known():
    assert len(R.BY_ID) == len(R.COMMANDS)
    keys = {k for k, _ in R.CATEGORIES}
    assert all(c.category in keys for c in R.COMMANDS)


def test_docs_match_registry():
    doc = (ROOT / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
    assert G.render(doc) == doc, "run: python scripts/gen_commands_doc.py"


def test_capabilities_phrase_short_and_mentions_notion():
    p = R.capabilities_phrase()
    assert "Notion" in p and len(p) < 450


@pytest.mark.parametrize("text,cid", [
    ("выруби экран", "monitor_off"), ("погаси экран", "monitor_off"), ("выключи экран", "monitor_off"),
    ("когда тренировка", "workout"), ("во сколько тренировка", "workout"), ("когда следующая тренировка", "workout"),
    ("что ты умеешь", "capabilities"), ("то есть что ты умеешь", "capabilities"),
    ("утренний брифинг", "tasks_briefing"), ("чё ещё осталось", "tasks_left"), ("перескажу все раздачи", "tasks_all"),
])
def test_live_feedback_phrases(listener, cfg, text, cid):
    assert R.route_id(listener.match_alias(text, cfg)) == cid
