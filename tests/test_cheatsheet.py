"""Cheat-sheet overlay: content from the catalogue and protocols, phrases, hotkey, toggle logic (fakes only)."""
import copy

import pytest

from command_fakes import FakeServices, run
from jarvis.adapters import overlay as OV
from jarvis.app.context import cheatsheet_content
from jarvis.app.settings import DEFAULTS
from jarvis.commands import catalog as CATALOG
from jarvis.core import cheatsheet as CS
from jarvis.core.routing import match_alias

CATALOG_MAP = {c.id: (c.summary, c.examples) for c in CATALOG.COMMANDS}


class FakePanel:
    def __init__(self): self.posted = []
    def post(self, message): self.posted.append(message)


class FakeHotkey:
    def __init__(self, bindings): self.bindings = list(bindings); self.registered = [True] * len(self.bindings)
    def stop(self): pass


GROUPS = [(key, title, [c.id for c in cmds]) for (key, _), (title, cmds) in zip(CATALOG.CATEGORIES, CATALOG.by_category(), strict=True)]


def make(cfg=None, panels=None, hotkeys=None, state_path=None):
    cfg = cfg if cfg is not None else copy.deepcopy(DEFAULTS)
    panels = panels if panels is not None else []
    def panel(events): p = FakePanel(); p.events = events; panels.append(p); return p
    def hotkey(bindings): h = FakeHotkey(bindings); (hotkeys if hotkeys is not None else []).append(h); return h
    return OV.Overlay(lambda: (CS.build(cfg, CATALOG_MAP, GROUPS), cfg), state_path, panel, hotkey), panels


def test_sections_come_from_the_protocols_and_the_catalogue():
    sections = CS.build(DEFAULTS, CATALOG_MAP)
    assert [s.title for s in sections] == ["Протоколы", "Основные команды"]
    protos = {ln.phrase: ln.effect for ln in sections[0].lines}
    assert protos["протокол спящая красавица [на …]"].startswith("ухожу спать или на созвон")
    assert protos["протокол бобик сдох"].startswith("конец работы")
    assert set(protos) >= {"протокол негры пашут", "протокол взлом пентагона"}
    cmds = {ln.phrase: ln.effect for ln in sections[1].lines}
    assert cmds["статус"] == CATALOG.BY_ID["status"].summary
    assert cmds["который час"] == ""   # a summary that only repeats the phrase is dropped
    assert "убери шпаргалку" in cmds and "какие протоколы" in cmds
    assert len(sections[1].lines) == len(DEFAULTS["overlay_commands"])
    assert [s.key for s in sections] == ["protocols", "main"]


def test_every_catalogue_command_is_in_a_category_section():
    sections = CS.build(DEFAULTS, CATALOG_MAP, GROUPS)
    cats = [s for s in sections if s.key.startswith("cat:")]
    assert [s.title for s in cats] == [t for _, t in CATALOG.CATEGORIES if any(c.category == _ for c in CATALOG.COMMANDS)]
    assert sum(len(s.lines) for s in cats) == len([c for c in CATALOG.COMMANDS if c.examples])


def test_every_default_overlay_command_is_in_the_catalogue():
    assert [i for i in CS.DEFAULTS["overlay_commands"] if i not in CATALOG.BY_ID] == []


def test_a_custom_protocol_without_summary_lists_its_steps_and_unknown_ids_are_skipped():
    cfg = dict(copy.deepcopy(DEFAULTS), protocols=[{"name": "Тест", "phrases": ["тихий час"], "steps": ["mute", "lock"], "confirm": True}],
               overlay_commands=["time", "nope"])
    s = CS.build(cfg, CATALOG_MAP)
    assert s[0].lines[0].phrase == "тихий час" and s[0].lines[0].effect == "без звука, блокировка (с подтверждением)"
    assert [ln.phrase for ln in s[1].lines] == ["который час"]
    text = CS.render_text(s)
    assert text.startswith(CS.TITLE) and "«тихий час» — без звука" in text


def test_app_content_rebuilds_from_the_live_config():
    class Store:
        cfg = copy.deepcopy(DEFAULTS)
        def load(self): return self.cfg
    store = Store(); content = cheatsheet_content(store)
    store.cfg = dict(store.cfg, overlay_commands=["time"])
    sections, cfg = content()
    assert cfg is store.cfg and [ln.phrase for ln in sections[1].lines] == ["который час"]
    assert len(sections) > 2 and sections[2].key.startswith("cat:")


@pytest.mark.parametrize("text,visible", [("покажи шпаргалку", True), ("Покажи шпаргалку!", True), ("закрой шпаргалку", False),
                                          ("убери шпаргалку", False), ("спрячь шпаргалку", False)])
def test_voice_phrases_route_to_the_overlay(cfg, text, visible):
    al = match_alias(text, cfg)
    assert al and al["action"] == "overlay" and al["visible"] is visible
    assert CATALOG.route_id(al) in CATALOG.BY_ID


def test_no_phrase_uses_a_word_missing_from_the_vosk_model():
    assert not any("скрой" in ph for ph in CS.phrases())


def test_grammar_has_the_phrases():
    names = {a["name"] for a in CS.aliases()}
    assert names == {"cheatsheet_show", "cheatsheet_hide"}
    assert set(CS.phrases()) >= {"покажи шпаргалку", "убери шпаргалку"}


@pytest.mark.parametrize("spec,expected", [("ctrl+alt+j", (0x0002 | 0x0001 | 0x4000, 0x4A)), ("Win+Shift+F1", (0x0008 | 0x0004 | 0x4000, 0x70)),
                                           ("", None), ("j", None), ("shift+j", None), ("ctrl+alt+ж", None), ("hyper+j", None), (None, None)])
def test_parse_hotkey(spec, expected):
    assert CS.parse_hotkey(spec) == expected


def test_corner_position_and_opacity_are_clamped():
    assert CS.position("top-right", (300, 200), (1920, 1040), 18) == (1602, 18)
    assert CS.position("bottom-left", (300, 200), (1920, 1040), 18) == (18, 822)
    assert CS.clamp((5000, -50), (300, 200), (0, 0, 1920, 1040)) == (1620, 0)
    assert CS.clamp((100, 100), (300, 200), (-1920, 0, 1920, 1080)) == (-300, 100)  # a monitor on the left
    assert CS.corner({"overlay_corner": "middle"}) == "top-right"
    assert CS.opacity({"overlay_opacity": 5}) == 1.0 and CS.opacity({"overlay_opacity": "x"}) == CS.DEFAULTS["overlay_opacity"]


def test_show_hide_toggle_post_to_one_lazy_panel():
    ov, panels = make()
    assert panels == [] and not ov.visible            # nothing is created until the first show
    assert ov.show() and ov.visible
    kind, (sections, cfg, state) = panels[0].posted[0]
    assert kind == "show" and sections[0].title == "Протоколы" and state.pinned is False
    assert panels[0].events is ov
    assert ov.toggle() is False and not ov.visible
    assert ov.toggle() is True
    assert len(panels) == 1 and [m[0] for m in panels[0].posted] == ["show", "hide", "show"]


def test_hide_before_show_creates_nothing_and_disabled_never_shows():
    ov, panels = make()
    assert ov.hide() is False and panels == []
    ov, panels = make(dict(copy.deepcopy(DEFAULTS), overlay_enabled=False))
    assert ov.show() is False and panels == [] and not ov.visible


def test_hotkeys_register_once_toggle_and_pin():
    hotkeys = []
    ov, panels = make(hotkeys=hotkeys)
    assert ov.start_hotkey(DEFAULTS) and not ov.start_hotkey(DEFAULTS)
    (show_keys, show), (pin_keys, pin) = hotkeys[0].bindings
    assert len(hotkeys) == 1 and show_keys == (0x4003, 0x4A) and pin_keys == (0x4007, 0x4A)
    show(); assert ov.visible
    show(); assert not ov.visible
    assert pin() is True and ov.visible and ov.state.pinned   # pinning a hidden panel shows it
    assert panels[0].posted[-1][1][2].pinned is True


def test_one_hotkey_is_enough():
    hotkeys = []
    ov, _ = make(hotkeys=hotkeys)
    assert ov.start_hotkey(dict(DEFAULTS, overlay_pin_hotkey=""))
    assert len(hotkeys[0].bindings) == 1


def test_pin_fold_and_move_persist_across_restarts(tmp_path):
    path = str(tmp_path / "cache" / "overlay.json")
    ov, panels = make(state_path=path)
    assert ov.state == CS.PanelState() and not ov.state.is_collapsed("protocols") and ov.state.is_collapsed("cat:pc")
    ov.show(); ov.toggle_pin(); ov.set_collapsed("protocols", True); ov.moved(40, 60)
    assert [m[0] for m in panels[0].posted] == ["show", "show", "show"]    # pin and fold redraw, a move does not
    again, _ = make(state_path=path)
    assert again.state == CS.PanelState(40, 60, True, {"protocols": True})
    assert again.state.is_collapsed("protocols")


def test_fold_while_hidden_does_not_show(tmp_path):
    ov, panels = make(state_path=str(tmp_path / "o.json"))
    ov.set_collapsed("main", True)
    assert panels == [] and not ov.visible


def test_broken_state_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "overlay.json"; path.write_text("{oops", encoding="utf-8")
    ov, _ = make(state_path=str(path))
    assert ov.state == CS.PanelState()
    assert CS.PanelState.from_json({"x": "1", "y": True, "pinned": 1, "collapsed": {"a": True, "b": "no"}}) == CS.PanelState(None, None, False, {"a": True})
    assert CS.PanelState.from_json([1]) == CS.PanelState()


def test_panel_fold_hides_the_body_by_its_own_key():
    st = CS.PanelState()
    assert not st.is_collapsed(CS.PANEL_KEY)
    st.collapsed[CS.PANEL_KEY] = True
    assert st.is_collapsed(CS.PANEL_KEY) and st.copy() == st and st.copy() is not st


def test_hotkey_off_when_empty_or_disabled():
    ov, _ = make()
    assert not ov.start_hotkey(dict(DEFAULTS, overlay_hotkey="", overlay_pin_hotkey=""))
    assert not ov.start_hotkey(dict(DEFAULTS, overlay_enabled=False))


def test_real_window_and_hotkey_are_guarded():
    with pytest.raises(AssertionError): OV.TkPanel(None)
    assert OV.HotkeyThread([((0, 0), lambda: None)]).registered == [False]


class FakeOverlay:
    def __init__(self, enabled=True): self.enabled, self.calls = enabled, []
    def show(self): self.calls.append("show"); return self.enabled
    def hide(self): self.calls.append("hide"); return True


def test_voice_handler_shows_and_hides(cfg):
    ov = FakeOverlay(); s = FakeServices(overlay=ov)
    run(match_alias("покажи шпаргалку", cfg), "покажи шпаргалку", cfg, s)
    run(match_alias("убери шпаргалку", cfg), "убери шпаргалку", cfg, s)
    assert ov.calls == ["show", "hide"] and s.said == ["Шпаргалка на экране, сэр.", "Убрал шпаргалку, сэр."]


def test_voice_handler_reports_a_disabled_or_missing_overlay(cfg):
    s = FakeServices(overlay=FakeOverlay(enabled=False))
    run(match_alias("покажи шпаргалку", cfg), "покажи шпаргалку", cfg, s)
    s2 = FakeServices(overlay=None)
    run(match_alias("убери шпаргалку", cfg), "убери шпаргалку", cfg, s2)
    assert s.said == s2.said == ["Шпаргалка выключена в настройках, сэр."]


def test_listener_registers_the_hotkey_with_the_inert_guard(app):
    assert isinstance(app.c.overlay, OV.Overlay)
    assert app.c.overlay.start_hotkey(DEFAULTS) is False   # conftest's inert hotkey never registers
