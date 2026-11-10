"""FatSecret OAuth1 client (stdlib only). Never logs credentials, URLs with tokens or response bodies."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from jarvis.adapters import credentials as CREDS
from jarvis.adapters import paths as PATHS

URL = "https://platform.fatsecret.com/rest/server.api"
NAMES = ("FATSECRET_CLIENT_ID", "FATSECRET_OAUTH1_CONSUMER_SECRET", "FATSECRET_ACCESS_TOKEN", "FATSECRET_ACCESS_SECRET")


def env_file() -> Path:
    return Path(os.environ.get("FATSECRET_ENV_FILE", str(PATHS.HOME / ".env")))


def _pct(s: object) -> str: return quote(str(s), safe="~")


def signed_params(method: str, extra: Mapping[str, Any], keys: Mapping[str, str]) -> dict[str, str]:
    """OAuth1 HMAC-SHA1 form parameters for one POST; reserved names cannot be overridden."""
    if any(str(k).startswith("oauth_") or k in ("method", "format") for k in extra): raise ValueError("Reserved parameter")
    key, secret, token, token_secret = (keys[k] for k in NAMES)
    p = {"oauth_consumer_key": key, "oauth_nonce": uuid.uuid4().hex, "oauth_signature_method": "HMAC-SHA1",
         "oauth_timestamp": str(int(time.time())), "oauth_token": token, "oauth_version": "1.0", "method": method, "format": "json"}
    p.update({str(k): str(v) for k, v in extra.items() if v is not None})
    norm = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(p.items()))
    signing = "&".join(("POST", _pct(URL), _pct(norm)))
    digest = hmac.new(f"{_pct(secret)}&{_pct(token_secret)}".encode(), signing.encode(), hashlib.sha1).digest()
    p["oauth_signature"] = base64.b64encode(digest).decode()
    return p


def call(method: str, extra: Mapping[str, Any]) -> dict[str, Any]:
    env = CREDS.fatsecret_env(dict(os.environ), env_file())
    if not all(env.get(k) for k in NAMES):
        raise ValueError("Missing OAuth1 credentials; check Windows Credential Manager or restricted environment file")
    p = signed_params(method, extra, env)
    req = Request(URL, data=urlencode(p).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urlopen(req, timeout=30) as response:
            result: dict[str, Any] = json.load(response)
            return result
    except HTTPError as exc:
        # Never output request URLs, headers, or exception bodies containing OAuth.
        raise ValueError(f"FatSecret HTTP {exc.code}") from None
