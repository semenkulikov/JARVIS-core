"""Optional neural stress marks (RUAccent), loaded once in the background warm-up."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Mapping

log = logging.getLogger("jarvis")


def _patch_sessions(obj: Any, depth: int = 0, seen: set[int] | None = None) -> None:
    """transformers>=5 tokenizers drop token_type_ids; add zeros if the onnx model needs them."""
    import numpy as _np
    seen = seen if seen is not None else set()
    if depth > 3 or id(obj) in seen: return
    seen.add(id(obj))
    for _name, v in list(getattr(obj, "__dict__", {}).items()):
        if type(v).__name__ == "InferenceSession":
            need = [i.name for i in v.get_inputs()]
            if "token_type_ids" in need and not getattr(v, "_jv_patched", False):
                orig = v.run

                def run(out_names: Any, feed: dict[str, Any], *a: Any, _orig: Any = orig, **k: Any) -> Any:
                    if "token_type_ids" not in feed and "input_ids" in feed:
                        feed = dict(feed); feed["token_type_ids"] = _np.zeros_like(feed["input_ids"])
                    return _orig(out_names, feed, *a, **k)
                v.run = run; v._jv_patched = True
        elif hasattr(v, "__dict__") and not isinstance(v, (str, bytes, int, float)):
            _patch_sessions(v, depth + 1, seen)


class Accentizer:
    """RUAccent wrapper: ``apply`` returns the text unchanged until ``load`` succeeded."""

    def __init__(self) -> None:
        self._obj: Any = None
        self.state = "off"          # off | disabled | ready | failed
        self.last_ms: float | None = None
        self._lock = threading.Lock()

    def load(self, cfg: Mapping[str, Any], base: str) -> None:
        if not cfg.get("stress_ruaccent", True):
            self.state = "disabled"; return
        with self._lock:
            if self._obj is not None: return
            try:
                t0 = time.time()
                from ruaccent import RUAccent
                a = RUAccent()
                wd = os.path.join(base, "models", "ruaccent"); os.makedirs(wd, exist_ok=True)
                a.load(omograph_model_size=cfg.get("ruaccent_model", "turbo3.1"), use_dictionary=bool(cfg.get("ruaccent_dictionary", True)),
                       device="CPU", workdir=wd, tiny_mode=bool(cfg.get("ruaccent_tiny_mode", False)))
                _patch_sessions(a)
                a.process_all("прогрев модели ударений, замок на двери.")
                self._obj = a; self.state = "ready"
                log.info("ruaccent loaded in %.1fs (%s)", time.time() - t0, cfg.get("ruaccent_model", "turbo3.1"))
            except Exception as e:
                self.state = "failed"; log.warning("ruaccent unavailable: %s", e)

    def apply(self, text: str) -> str:
        a = self._obj
        if a is None: return text
        try:
            t0 = time.time()
            out = " ".join(str(a.process_all(p)) for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip())
            self.last_ms = (time.time() - t0) * 1000
            log.info("ruaccent %.0f ms (%d chars)", self.last_ms, len(text))
            return out
        except Exception as e:
            log.warning("ruaccent failed: %s", e); return text
