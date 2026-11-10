"""Follow-up without the wake word: typed settings and the listening window."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from jarvis.core import gate as GATE


@dataclass(frozen=True)
class FollowupSettings:
    enabled: bool
    max_turns: int
    echo_guard_s: float
    min_conf: float
    window_s: float
    question_window_s: float
    cap_s: float

    @classmethod
    def from_cfg(cls, cfg: Mapping[str, Any]) -> FollowupSettings:
        return cls(enabled=bool(cfg.get("followup_enabled", True)),
                   max_turns=max(0, int(cfg.get("followup_max_turns", 8))),
                   echo_guard_s=max(0.0, min(2.0, float(cfg.get("followup_echo_guard_s", 0.3)))),
                   min_conf=float(cfg.get("followup_min_conf", 0.65)),
                   window_s=float(cfg.get("followup_window_s", 7)),
                   question_window_s=float(cfg.get("followup_question_window_s", 10)),
                   cap_s=float(GATE.setting(cfg, "followup_window_cap_s")))

    def window_for(self, spoken: str | None) -> float:
        """Seconds to listen after ``spoken``: longer after a question, never above the cap."""
        base = self.question_window_s if (spoken or "").rstrip().endswith("?") else self.window_s
        return max(0.0, min(30.0, self.cap_s, base))


def followup_seconds(cfg: Mapping[str, Any], spoken: str | None) -> float:
    return FollowupSettings.from_cfg(cfg).window_for(spoken)
