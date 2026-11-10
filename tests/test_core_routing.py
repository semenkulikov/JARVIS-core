from jarvis.core.routing import READ_ONLY_ACTIONS, Router, match_alias
from jarvis.core.state import ListenerState


def test_filler_is_ignored_unless_a_shutdown_waits_for_confirmation(cfg):
    st = ListenerState()
    assert Router(st).choose("да сэр", 1.0, "", cfg) == ("", False)
    assert Router(st, shutdown_pending=lambda: True).choose("да сэр", 1.0, "", cfg) != ("", False)


def test_drop_marks_the_turn_silent(cfg):
    st = ListenerState(last_capture=None)
    assert Router(st).choose("в вашем", 0.9, "", cfg) == ("", False) and st.dropped


def test_read_only_actions_route_locally(cfg):
    assert match_alias("который час", cfg)["action"] in READ_ONLY_ACTIONS
