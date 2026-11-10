import pytest

from jarvis.app.settings import DEFAULT_ALIASES
from jarvis.core.config import merge_aliases


def test_user_aliases_keep_new_default_phrases():
    user = [{"name": "monitor_off", "phrases": ["выключи экран"], "action": "monitor_off"},
            {"name": "mine", "phrases": ["моя фраза"], "action": "say"}]
    merged = merge_aliases(user, DEFAULT_ALIASES)
    mon = next(a for a in merged if a["name"] == "monitor_off")
    assert "выруби экран" in mon["phrases"] and mon["phrases"][0] == "выключи экран"
    assert any(a["name"] == "mine" for a in merged) and any(a["name"] == "workout" for a in merged)
    replaced = merge_aliases([dict(user[0], replace=True)], DEFAULT_ALIASES)
    assert next(a for a in replaced if a["name"] == "monitor_off")["phrases"] == ["выключи экран"]


@pytest.mark.parametrize("text,name", [("выруби экран", "monitor_off"), ("погаси экран", "monitor_off"), ("выключи экран", "monitor_off"),
                                       ("отключи экран", "monitor_off"), ("когда тренировка", "workout"), ("во сколько тренировка", "workout"),
                                       ("когда следующая тренировка", "workout")])
def test_screen_and_workout_phrases(listener, cfg, text, name):
    assert listener.match_alias(text, cfg)["name"] == name
