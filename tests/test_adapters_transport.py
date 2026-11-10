import urllib.error

import pytest

from jarvis.adapters import transport as T
from jarvis.core.state import RequestLedger, Signals


def test_placeholder_and_auth_cleaning():
    assert T.placeholder({"webhook_url": ""}) and T.placeholder({"webhook_url": "https://x/PASTE"})
    assert not T.placeholder({"webhook_url": "https://example.invalid/hook", "webhook_auth_header": "Bearer t"})
    assert T.clean_auth('\ufeff"Authorization: Bearer abc\r\n"') == "Bearer abc"


def test_post_retry_stops_on_client_errors(monkeypatch):
    tr = T.WebhookTransport(Signals(), RequestLedger()); calls = []
    def post(cfg, payload):
        calls.append(1); raise urllib.error.HTTPError("u", 401, "no", {}, None)
    monkeypatch.setattr(tr, "post", post)
    with pytest.raises(urllib.error.HTTPError):
        tr.post_retry({}, {"request_id": "r"})
    assert calls == [1]


def test_post_retry_skips_abandoned_requests():
    led = RequestLedger(); led.cancel("r")
    assert T.WebhookTransport(Signals(), led).post_retry({}, {"request_id": "r"}) is None


def test_unconfigured_server_is_not_called(monkeypatch):
    tr = T.WebhookTransport(Signals(), RequestLedger())
    monkeypatch.setattr(tr, "post_retry", lambda *a, **k: pytest.fail("must not post"))
    assert tr.call("r", "x", "test", {"webhook_url": ""}, True) is False
