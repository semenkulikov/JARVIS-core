"""FatSecret OAuth1 CLI. Uses only Python stdlib; never logs credentials."""
import argparse, base64, hashlib, hmac, json, os, time, uuid
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

URL = "https://platform.fatsecret.com/rest/server.api"

def jarvis_credentials_path():
    from jarvis.adapters.paths import HOME
    return HOME / ".env"

def call(method, extra):
    import sys
    voice=Path(__file__).resolve().parent
    if str(voice) not in sys.path:sys.path.insert(0,str(voice))
    from jarvis.adapters import credentials as CREDS
    env = CREDS.fatsecret_env(dict(os.environ),Path(os.environ.get('FATSECRET_ENV_FILE', str(jarvis_credentials_path()))))
    names = ["FATSECRET_CLIENT_ID", "FATSECRET_OAUTH1_CONSUMER_SECRET", "FATSECRET_ACCESS_TOKEN", "FATSECRET_ACCESS_SECRET"]
    if not all(env.get(k) for k in names):
        raise ValueError("Missing OAuth1 credentials; check Windows Credential Manager or restricted environment file")
    key, secret, token, token_secret = [env[k] for k in names]
    if any(str(k).startswith("oauth_") or k in ("method", "format") for k in extra):
        raise ValueError("Reserved parameter")
    p = {"oauth_consumer_key":key,"oauth_nonce":uuid.uuid4().hex,"oauth_signature_method":"HMAC-SHA1","oauth_timestamp":str(int(time.time())),"oauth_token":token,"oauth_version":"1.0","method":method,"format":"json"}
    p.update({str(k):str(v) for k,v in extra.items() if v is not None})
    pct = lambda s: quote(str(s), safe="~")
    norm = "&".join(f"{pct(k)}={pct(v)}" for k,v in sorted(p.items()))
    signing = "&".join(("POST",pct(URL),pct(norm)))
    p["oauth_signature"] = base64.b64encode(hmac.new(f"{pct(secret)}&{pct(token_secret)}".encode(), signing.encode(), hashlib.sha1).digest()).decode()
    req = Request(URL, data=urlencode(p).encode(), headers={"Content-Type":"application/x-www-form-urlencoded"},method="POST")
    try:
        with urlopen(req, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        # Never output request URLs, headers, or exception bodies containing OAuth.
        raise ValueError(f"FatSecret HTTP {exc.code}") from None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("method")
    parser.add_argument("params", nargs="?", default="{}", help="JSON object")
    parser.add_argument("--params-file")
    args = parser.parse_args()
    try:
        raw = Path(args.params_file).read_text(encoding="utf-8-sig") if args.params_file else args.params
        params = json.loads(raw)
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
        result = call(args.method, params)
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(2 if isinstance(result,dict) and "error" in result else 0)
    except (ValueError, OSError) as exc:
        # Network exceptions can include URLs; display type only except known ValueError.
        message = str(exc) if type(exc) is ValueError else type(exc).__name__
        print(json.dumps({"local_error":message}, ensure_ascii=True))
        raise SystemExit(1) from None
