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
    def __init__(self, keys, callback, registered=True): self.keys, self.callback, self.registered = keys, callback, registered
    def stop(self): pass


def make(cfg=None, panels=None, hotkeys=None):
    cfg = cfg if cfg is not None else copy.deepcopy(DEFAULTS)
    panels = panels if panels is not None else []
    def panel(): p = FakePanel(); panels.append(p); return p
    def hotkey(keys, cb): h = FakeHotkey(keys, cb); (hotkeys if hotkeys is not None else []).append(h); return h
    return OV.Overlay(lambda: (CS.build(cfg, CATALOG_MAP), cfg), panel, hotkey), panels


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
    assert "скрой шпаргалку" in cmds and "какие протоколы" in cmds
    assert len(sections[1].lines) == len(DEFAULTS["overlay_commands"])


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


@pytest.mark.parametrize("text,visible", [("покажи шпаргалку", True), ("Покажи шпаргалку!", True), ("скрой шпаргалку", False),
                                          ("убери шпаргалку", False), ("спрячь шпаргалку", False)])
def test_voice_phrases_route_to_the_overlay(cfg, text, visible):
    al = match_alias(text, cfg)
    assert al and al["action"] == "overlay" and al["visible"] is visible
    assert CATALOG.route_id(al) in CATALOG.BY_ID


def test_grammar_has_the_phrases():
    names = {a["name"] for a in CS.aliases()}
    assert names == {"cheatsheet_show", "cheatsheet_hide"}
    assert set(CS.phrases()) >= {"покажи шпаргалку", "скрой шпаргалку"}


@pytest.mark.parametrize("spec,expected", [("ctrl+alt+j", (0x0002 | 0x0001 | 0x4000, 0x4A)), ("Win+Shift+F1", (0x0008 | 0x0004 | 0x4000, 0x70)),
                                           ("", None), ("j", None), ("shift+j", None), ("ctrl+alt+ж", None), ("hyper+j", None), (None, None)])
def test_parse_hotkey(spec, expected):
    assert CS.parse_hotkey(spec) == expected


def test_corner_position_and_opacity_are_clamped():
    assert CS.position("top-right", (300, 200), (1920, 1040), 18) == (1602, 18)
    assert CS.position("bottom-left", (300, 200), (1920, 1040), 18) == (18, 782)
    assert CS.corner({"overlay_corner": "middle"}) == "top-right"
    assert CS.opacity({"overlay_opacity": 5}) == 1.0 and CS.opacity({"overlay_opacity": "x"}) == CS.DEFAULTS["overlay_opacity"]


def test_show_hide_toggle_post_to_one_lazy_panel():
    ov, panels = make()
    assert panels == [] and not ov.visible            # nothing is created until the first show
    assert ov.show() and ov.visible
    kind, (sections, cfg) = panels[0].posted[0]
    assert kind == "show" and sections[0].title == "Протоколы"
    assert ov.toggle() is False and not ov.visible
    assert ov.toggle() is True
    assert len(panels) == 1 and [m[0] for m in panels[0].posted] == ["show", "hide", "show"]


def test_hide_before_show_creates_nothing_and_disabled_never_shows():
    ov, panels = make()
    assert ov.hide() is False and panels == []
    ov, panels = make(dict(copy.deepcopy(DEFAULTS), overlay_enabled=False))
    assert ov.show() is False and panels == [] and not ov.visible


def test_hotkey_registers_once_and_toggles():
    hotkeys = []
    ov, panels = make(hotkeys=hotkeys)
    assert ov.start_hotkey(DEFAULTS) and not ov.start_hotkey(DEFAULTS)
    assert len(hotkeys) == 1 and hotkeys[0].keys == (0x4003, 0x4A)
    hotkeys[0].callback(); assert ov.visible
    hotkeys[0].callback(); assert not ov.visible


def test_hotkey_off_when_empty_or_disabled():
    ov, _ = make()
    assert not ov.start_hotkey(dict(DEFAULTS, overlay_hotkey=""))
    assert not ov.start_hotkey(dict(DEFAULTS, overlay_enabled=False))


def test_real_window_and_hotkey_are_guarded():
    with pytest.raises(AssertionError): OV.TkPanel()
    assert OV.HotkeyThread((0, 0), lambda: None).registered is False


class FakeOverlay:
    def __init__(self, enabled=True): self.enabled, self.calls = enabled, []
    def show(self): self.calls.append("show"); return self.enabled
    def hide(self): self.calls.append("hide"); return True


def test_voice_handler_shows_and_hides(cfg):
    ov = FakeOverlay(); s = FakeServices(overlay=ov)
    run(match_alias("покажи шпаргалку", cfg), "покажи шпаргалку", cfg, s)
    run(match_alias("скрой шпаргалку", cfg), "скрой шпаргалку", cfg, s)
    assert ov.calls == ["show", "hide"] and s.said == ["Шпаргалка на экране, сэр.", "Убрал шпаргалку, сэр."]


def test_voice_handler_reports_a_disabled_or_missing_overlay(cfg):
    s = FakeServices(overlay=FakeOverlay(enabled=False))
    run(match_alias("покажи шпаргалку", cfg), "покажи шпаргалку", cfg, s)
    s2 = FakeServices(overlay=None)
    run(match_alias("скрой шпаргалку", cfg), "скрой шпаргалку", cfg, s2)
    assert s.said == s2.said == ["Шпаргалка выключена в настройках, сэр."]


def test_listener_registers_the_hotkey_with_the_inert_guard(app):
    assert isinstance(app.c.overlay, OV.Overlay)
    assert app.c.overlay.start_hotkey(DEFAULTS) is False   # conftest's inert hotkey never registers
