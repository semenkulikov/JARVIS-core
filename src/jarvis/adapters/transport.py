"""Transport to the user's server: one JSON POST per request, retried briefly; replies come via the outbox."""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from typing import Any

from jarvis.core import codemode as CODE
from jarvis.core.state import RequestLedger, Signals

Config = dict[str, Any]
log = logging.getLogger("jarvis")

# Optional payload fields a caller may forward; anything else never leaves the machine.
ALLOWED_EXTRA = frozenset({"task_text", "clipboard_text", "clipboard_truncated", "context_source", "target_language", "food_text",
                           "confirmation_policy", "local_date", "timezone", "reply_mode", "outbox_file", "presence_at",
                           "idle_seconds", "expires_iso", "intent", "style", "local_time", "weekday"}) | CODE.PAYLOAD_FIELDS


def placeholder(cfg: Config) -> bool:
    """No real server configured (empty, not http(s), or the example's PASTE marker)."""
    u = str(cfg.get("webhook_url", "")).strip(); a = str(cfg.get("webhook_auth_header", ""))
    return urllib.parse.urlparse(u).scheme not in ("http", "https") or "PASTE" in u or "PASTE" in a


def clean_auth(h: Any) -> str:
    h = str(h or "").replace("\ufeff", "").strip().strip('"').strip("'").strip()
    h = re.sub(r"^authorization\s*:\s*", "", h, flags=re.I).strip()
    return re.sub(r"[\r\n]", "", h)


class WebhookTransport:
    """Implements :class:`jarvis.core.ports.ServerTransport`."""

    def __init__(self, signals: Signals, ledger: RequestLedger) -> None:
        self.signals, self.ledger = signals, ledger

    def post(self, cfg: Config, payload: dict[str, Any]) -> int:
        url = str(cfg["webhook_url"]).replace("\ufeff", "").strip().strip('"').strip("'").strip()
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            raise ValueError("webhook_url_scheme")
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Authorization": clean_auth(cfg["webhook_auth_header"])})
        with urllib.request.urlopen(req, timeout=25) as r:
            return int(r.status)

    def post_retry(self, cfg: Config, payload: dict[str, Any], total: float = 30, independent: bool = False) -> int | None:
        """Retry network errors and 5xx/429 for ``total`` s; None when the request was cancelled meanwhile.

        Stopping speech is not cancelling: only the ledger says a request was abandoned."""
        t0 = time.time(); err: Exception | None = None
        while time.time() - t0 < total:
            if not independent and self.ledger.is_cancelled(payload.get("request_id")): return None
            try: return self.post(cfg, payload)
            except Exception as e:
                err = e; log.warning("webhook attempt failed: %s code=%s", type(e).__name__, getattr(e, "code", None))
                if isinstance(e, ValueError): break
                code = getattr(e, "code", None)
                if code and 400 <= int(code) < 500 and int(code) != 429: break
                time.sleep(3)
        if err is None: raise TimeoutError("webhook retry window closed")
        raise err

    def call(self, rid: str, text: str, trigger: str, cfg: Config, test: bool, listener_ack: str = "", kind: str = "free",
             trace: Any = None, extra_payload: dict[str, Any] | None = None) -> bool:
        payload = {"request_id": rid, "text": text, "trigger": trigger, "listener_ack": listener_ack, "kind": kind}
        payload.update({k: v for k, v in (extra_payload or {}).items() if k in ALLOWED_EXTRA})
        if placeholder(cfg):
            log.warning("webhook not configured; request_id=%s kind=%s", rid, kind)
            return False
        if trace is not None: trace.mark("post_start")
        try:
            t0 = time.monotonic(); log.info("webhook POST start rid=%s", rid)
            status = self.post_retry(cfg, payload, independent=True) if kind == "morning_briefing" else self.post_retry(cfg, payload)
            if trace is not None: trace.mark("post_done")
            log.info("webhook status %s (rid=%s) post_s=%.3f", status, rid, time.monotonic() - t0)
            return status is not None and 200 <= status < 300
        except Exception as e:
            log.error("webhook failed: %s code=%s", type(e).__name__, getattr(e, "code", None)); return False
