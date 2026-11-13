import pytest

from jarvis.app.settings import DEFAULT_ALIASES
from jarvis.commands import registry
from jarvis.core.phrases import SMALLTALK_ALIASES
from command_fakes import FakeServices, run

# Actions produced in code rather than by the alias table (jarvis.core.routing, jarvis.core.tasks, sleep, DND).
ROUTED_ACTIONS = {"jarvis_sleep", "awake", "capabilities", "tasks", "proactive_dnd", "quick2", "webhook", "status", "cache_field", "say"}


def test_every_action_has_a_handler():
    handlers = registry.load_builtin()
    actions = {a.get("action", "say") for a in DEFAULT_ALIASES + SMALLTALK_ALIASES} | ROUTED_ACTIONS
    assert actions - set(handlers) == set()
    assert {fn.__module__.rsplit(".", 1)[-1] for fn in handlers.values()} == {"conversation", "day", "modes", "pc", "protocols", "server"}


def test_one_owner_per_action():
    registry.load_builtin()
    with pytest.raises(ValueError, match="already handled"):
        registry.handles("battery")(lambda ctx, al: None)


def test_new_module_registers_without_touching_the_loop(cfg):
    seen = []
    @registry.handles("test_only_action")
    def handler(ctx, al): seen.append((ctx.text, al["x"]))
    try:
        run({"name": "t", "action": "test_only_action", "x": 1}, "проверка", cfg, FakeServices())
    finally:
        registry.HANDLERS.pop("test_only_action")
    assert seen == [("проверка", 1)]


def test_unknown_action_speaks_the_reply(cfg, caplog):
    s = FakeServices()
    with caplog.at_level("INFO", logger="jarvis"):
        run({"name": "x", "action": "no_such_action", "reply": "Готово, сэр."}, "сделай", cfg, s)
    assert s.said == ["Готово, сэр."] and "ALIAS x (no_such_action) <- 'сделай'" in caplog.text


def test_key_in_test_mode_acks_without_pressing(cfg):
    s = FakeServices()
    run({"name": "v", "action": "key", "key": "vol_up"}, "громче", cfg, s, test=True)
    assert s.said == ["<ack_command>"]


def test_timer_without_duration_asks(cfg):
    s = FakeServices()
    run({"name": "t", "action": "timer"}, "поставь таймер", cfg, s)
    assert s.said == ["На сколько поставить таймер, сэр?"]


def test_timer_cancel_counts(cfg):
    class Ctl:
        timers = type("T", (), {"cancel": lambda self: 0})()
    s = FakeServices(controller=Ctl())
    run({"name": "t", "action": "timer_cancel"}, "отмени таймер", cfg, s)
    assert s.said == ["Активных таймеров нет, сэр."]


def test_webhook_alias_forwards_target_and_reply(cfg):
    s = FakeServices()
    run({"name": "w", "action": "webhook", "target": "погода", "reply": "Смотрю, сэр."}, "какая погода", cfg, s)
    assert s.asked == [("погода", {"ack": "Смотрю, сэр."})]


@pytest.mark.parametrize("text,secs", [("поставь таймер на пять минут", 300), ("таймер 10", 600), ("таймер на полторы минуты", 90),
                                       ("таймер на час", 3600)])
def test_timer_alias_uses_the_quick_duration_parser(cfg, text, secs):
    added = []

    class Ctl:
        timers = type("T", (), {"add": lambda self, s, label: added.append(s)})()
    s = FakeServices(controller=Ctl())
    run({"name": "t", "action": "timer"}, text, cfg, s)
    assert added == [secs] and s.said[0].startswith("Таймер на ")
