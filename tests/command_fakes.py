"""Fake Services for command handler tests: records speech and server requests, no audio or HTTP."""
from __future__ import annotations

from jarvis.adapters import laptop as LAPTOP
from jarvis.commands.base import CommandContext
from jarvis.commands import registry
from jarvis.core.phrases import Picker
from jarvis.core.state import ListenerState


class FakeServices:
    def __init__(self, status=None, controller=None, sleep=None, proactive=None, laptop=None):
        self.state = ListenerState(); self.status = status; self.picker = Picker({})
        self.said, self.replies, self.asked = [], [], []
        self._controller, self._sleep, self._proactive = controller, sleep, proactive
        self._laptop = laptop if laptop is not None else LAPTOP  # guarded by conftest

    def say(self, text, cfg, role="reply", private=False):
        self.said.append(text); return True

    def say_reply(self, text, cfg, private=False):
        self.replies.append(text)

    def ask_server(self, text, cfg, trig, test, **kw):
        self.asked.append((text, kw))

    def stop_reply(self):
        self.stopped_reply = True

    def pick(self, cfg, key):
        return f"<{key}>"

    def controller(self): return self._controller
    def sleep(self): return self._sleep
    def proactive(self): return self._proactive
    def laptop(self): return self._laptop


def run(al, text, cfg, services, test=False, trig="wake_word"):
    registry.load_builtin()
    registry.dispatch(CommandContext(text, cfg, trig, test, services), al)
