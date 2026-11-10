"""FatSecret OAuth1 CLI: ``python src/fatsecret_call.py <method> [json] [--params-file f]``.

A thin entry point kept for external callers; the client is jarvis.adapters.fatsecret.
Prints one JSON object; never prints credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis.adapters.fatsecret import call  # noqa: E402

__all__ = ["call", "main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("method")
    parser.add_argument("params", nargs="?", default="{}", help="JSON object")
    parser.add_argument("--params-file")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.params_file).read_text(encoding="utf-8-sig") if args.params_file else args.params
        params = json.loads(raw)
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
        result = call(args.method, params)
        print(json.dumps(result, ensure_ascii=True))
        return 2 if isinstance(result, dict) and "error" in result else 0
    except (ValueError, OSError) as exc:
        # Network exceptions can include URLs; display type only except known ValueError.
        message = str(exc) if type(exc) is ValueError else type(exc).__name__
        print(json.dumps({"local_error": message}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
