"""Score the owner's calibration recordings through the real listener pipeline.

    python scripts/eval_calibration.py --home C:\\Jarvis\\voice                 # newest calibration folder
    python scripts/eval_calibration.py --home ... --dir <folder> --set wake_verify_normalize=false

Per clip: wake candidate (Vosk wake grammar and openWakeWord, as in the listener loop), the free
wake verify, the owner-voice score, and for commands the real capture (free + grammar recognizer),
Router.choose and match_alias compared with the reference phrase. Room background gives the
impostor side of the speaker scores. --set overrides config keys to compare settings; results go
to <folder>/eval-<label>.json next to the recordings (never into the repository).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from jarvis.adapters.asr_vosk import VoskASR  # noqa: E402
from jarvis.adapters.audio import CHUNK, SR, Capture, frames_after  # noqa: E402
from jarvis.adapters.speaker import SpeakerVerifier  # noqa: E402
from jarvis.app import settings  # noqa: E402
from jarvis.core import gate as GATE  # noqa: E402
from jarvis.core import voiceprint as VP  # noqa: E402
from jarvis.core.routing import Router, match_alias  # noqa: E402
from jarvis.core.state import ListenerState  # noqa: E402
from jarvis.core.wake import VOSK_WAKE_SKIP_S, VOSK_WAKE_TAIL_S  # noqa: E402

Config = dict[str, Any]
ROUTE_KEYS_IGNORED = ("target", "text", "reply", "phrases", "food_text")


# ------------------------------------------------------------------ pure helpers
def route_key(alias: Optional[dict[str, Any]]) -> Optional[str]:
    """What the phrase would do, without the transcript-specific fields; None means «sent to the server»."""
    if not alias: return None
    kept = {k: v for k, v in alias.items() if k not in ROUTE_KEYS_IGNORED and not k.startswith("_")}
    return json.dumps(kept, ensure_ascii=False, sort_keys=True, default=str)


def reference_text(item: dict[str, Any]) -> str:
    """The command part of a manifest phrase («Джарвис … что ты умеешь» -> «что ты умеешь»)."""
    text = str(item.get("text", ""))
    return text.split("…", 1)[1].strip() if "…" in text else text


def parse_overrides(pairs: Iterable[str]) -> Config:
    out: Config = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        try: out[key.strip()] = json.loads(raw)
        except ValueError: out[key.strip()] = raw
    return out


def quiet_background(silence: Optional[np.ndarray], seconds: float) -> np.ndarray:
    """The calmest stretch of the recorded room (zeros when there is none) to frame each clip like live audio."""
    n = int(seconds * SR)
    if silence is None or len(silence) < n: return np.zeros(n, dtype=np.float32)
    frames = len(silence) // n
    best = min(range(frames), key=lambda i: float(np.sqrt(np.mean(silence[i * n:(i + 1) * n] ** 2))))
    return silence[best * n:(best + 1) * n].astype(np.float32)


def background_windows(silence: Optional[np.ndarray], seconds: float, hop: float = 0.5) -> list[np.ndarray]:
    if silence is None: return []
    n, h = int(seconds * SR), int(hop * SR)
    return [silence[i:i + n] for i in range(0, max(0, len(silence) - n) + 1, h)]


def percentiles(values: list[float]) -> dict[str, float]:
    if not values: return {}
    v = np.asarray(values, dtype=np.float64)
    return {"n": float(len(v)), "min": round(float(v.min()), 3), "p10": round(float(np.percentile(v, 10)), 3),
            "median": round(float(np.median(v)), 3), "max": round(float(v.max()), 3)}


def summarize(rows: list[dict[str, Any]], impostor: list[float]) -> dict[str, Any]:
    wake = [r for r in rows if r["kind"] in ("wake", "wake_command")]
    cmds = [r for r in rows if r["kind"] in ("command", "wake_command") and "command" in r]
    owner = [r["speaker"] for r in rows if r.get("speaker") is not None]
    return {
        "wake_candidates": sum(bool(r["wake"]["candidate"]) for r in wake), "wake_triggered": sum(bool(r["wake"]["triggered"]) for r in wake),
        "wake_total": len(wake),
        "verify_rejected": sum(r["wake"]["candidate"] and r["wake"]["verify"] is False for r in wake),
        "speaker_rejected": sum(r["wake"]["candidate"] and r["wake"]["verify"] and r["wake"]["speaker_ok"] is False for r in wake),
        "commands_correct": sum(bool(r["command"]["correct"]) for r in cmds), "commands_total": len(cmds),
        "owner_scores": percentiles(owner), "background_scores": percentiles(impostor),
        "background_wake_triggers": None,
        "wake_speaker_scores": percentiles([r["wake"]["speaker_score"] for r in wake if r["wake"].get("speaker_score") is not None]),
    }


def suggest_speaker_threshold(owner: list[float], impostor: list[float]) -> Optional[dict[str, float]]:
    """Midway between the owner's 10th percentile and the loudest background window, with both margins."""
    if not owner: return None
    lo = float(np.percentile(owner, 10)); hi = max(impostor) if impostor else 0.0
    t = (lo + hi) / 2
    return {"threshold": round(t, 3), "owner_p10": round(lo, 3), "background_max": round(hi, 3),
            "margin_owner": round(lo - t, 3), "margin_background": round(t - hi, 3),
            "owner_rejected": float(sum(o < t for o in owner))}


# ------------------------------------------------------------------ the pipeline
@dataclass
class Pipeline:
    home: Path
    cfg: Config
    asr: VoskASR
    router: Router
    speaker: SpeakerVerifier
    oww_factory: Optional[Callable[[], Any]] = None
    log: list[str] = field(default_factory=list)
    last_score: Optional[float] = None
    background_triggers: int = 0

    @classmethod
    def load(cls, home: Path, cfg: Config) -> "Pipeline":
        state = ListenerState(); asr = VoskASR(state); asr.quiet()
        models = home / "models"
        state.model = asr.load_model(str(models / next(d for d in os.listdir(models) if d.startswith("vosk-model"))))
        oww_factory: Optional[Callable[[], Any]] = None
        if cfg.get("oww_enabled"):
            try:
                from openwakeword.model import Model as OWW
                from jarvis.app.listener import OWW_MODEL
                path = str(models / OWW_MODEL)
                OWW(wakeword_models=[path], inference_framework="onnx")
                oww_factory = lambda: OWW(wakeword_models=[path], inference_framework="onnx")  # noqa: E731
            except Exception as e:
                print("openWakeWord unavailable: %s" % e)
        scfg = dict(cfg, speaker_verify_enabled=True)
        return cls(home, cfg, asr, Router(state), SpeakerVerifier(home, scfg), oww_factory)

    def speaker_score(self, audio: np.ndarray) -> Optional[float]:
        self.speaker.cfg = dict(self.cfg, speaker_verify_enabled=True)
        return self.speaker.check(audio)[1]

    def wake(self, audio: np.ndarray, bg: np.ndarray) -> dict[str, Any]:
        out = self._wake(audio, bg); out["speaker_score"] = self.last_score
        return out

    def background_wakes(self, silence: np.ndarray, bg: np.ndarray, seconds: float = 3.0) -> int:
        """Wake triggers on the recorded room background, cut into listener-sized pieces (should be 0)."""
        n = int(seconds * SR)
        return sum(bool(self._wake(silence[i:i + n], bg)["triggered"]) for i in range(0, len(silence) - n + 1, n))

    def _wake(self, audio: np.ndarray, bg: np.ndarray) -> dict[str, Any]:
        """The listener's wake path over [background, clip, background]: candidate, verify, owner voice."""
        cfg = self.cfg; x = np.concatenate([bg, audio, bg, bg]).astype(np.float32); self.last_score = None
        ring: list[tuple[int, np.ndarray]] = []; pos = 0
        wrec = self.asr.wake_recognizer(); oww = self.oww_factory() if self.oww_factory else None
        check: Optional[dict[str, Any]] = None
        out: dict[str, Any] = {"candidate": False, "conf": None, "oww": 0.0, "verify": None, "speaker_ok": None,
                               "triggered": False, "frm": None, "skip": 0.0}
        for i in range(0, len(x) - CHUNK + 1, CHUNK):
            chunk = x[i:i + CHUNK]; st = pos; pos += len(chunk); ring.append((st, chunk))
            i16 = (np.clip(chunk, -1, 1) * 32767).astype(np.int16)
            sc = float(max(oww.predict(i16).values())) if oww is not None else 0.0
            out["oww"] = max(out["oww"], round(sc, 3))
            if sc >= cfg["oww_threshold"] and check is None:
                frm = st + len(chunk) - int(cfg["wake_prebuffer_s"] * SR); out["candidate"] = True
                if sc >= float(GATE.setting(cfg, "oww_strong_threshold")):
                    strong = self.speaker_ok(ring, pos)
                    out.update(verify=True, speaker_ok=strong, triggered=strong, frm=frm, ring=ring); return out
                check = {"a": frm, "b": pos + int(0.3 * SR), "frm": frm, "src": "oww"}
            if wrec.AcceptWaveform(i16.tobytes()):
                ws = [w for w in json.loads(wrec.Result()).get("result", []) if w.get("word") == "джарвис"]
                if ws:
                    out["conf"] = round(float(ws[0].get("conf", 0)), 3)
                    if ws[0].get("conf", 0) >= cfg["vosk_wake_min_conf"] and (check is None or check["src"] == "oww"):
                        out["candidate"] = True
                        check = {"a": int((ws[0]["start"] - float(GATE.setting(cfg, "wake_verify_pre_s"))) * SR),
                                 "b": int((ws[-1]["end"] + float(GATE.setting(cfg, "wake_verify_post_s"))) * SR),
                                 "frm": int(ws[-1]["end"] * SR) - int(VOSK_WAKE_TAIL_S * SR), "src": "vosk"}
            if check is not None and pos >= check["b"]:
                verified = self.asr.verify_wake(ring, check["a"], check["b"], cfg, owner=self._owner(ring, int(check["b"])))
                owner = self.speaker_ok(ring, check["b"]) if verified else None
                out.update(verify=verified, speaker_ok=owner, triggered=bool(verified and owner), frm=check["frm"],
                           skip=VOSK_WAKE_SKIP_S if check["src"] == "vosk" else 0.0, ring=ring)
                return out
        return out

    def _owner(self, ring: list[tuple[int, np.ndarray]], end: int) -> Callable[[], bool]:
        """Like SpeakerGate.owner_confirmed: True only when the owner's voice was actually scored."""
        def confirmed() -> bool:
            return self.speaker_ok(ring, end) and self.last_score is not None
        return confirmed

    def speaker_ok(self, ring: list[tuple[int, np.ndarray]], end: int) -> bool:
        """The listener's owner check on the window that ends at the wake word; the score is kept in ``last_score``."""
        from jarvis.adapters.audio import ring_audio
        self.speaker.cfg = dict(self.cfg, speaker_verify_enabled=True)
        ok, self.last_score = self.speaker.check(ring_audio(ring, end - int(float(self.speaker.setting("speaker_window_s")) * SR), end))
        return bool(ok) if self.cfg.get("speaker_verify_enabled") else True

    def command(self, chunks: list[np.ndarray], reference: str, skip_s: float = 0.0) -> dict[str, Any]:
        """The real capture over pre-recorded frames, then Router.choose and match_alias as in a turn."""
        cfg = self.cfg; cap = Capture(chunks)
        text, conf, gtext = self.asr.capture(cap, cfg, float(cfg["phrase_wait_s"]), skip_s)
        chosen, ok = self.router.choose(text, conf, gtext, cfg)
        want = route_key(match_alias(reference, cfg)); got = route_key(match_alias(chosen, cfg)) if ok and chosen else None
        return {"free": text, "conf": round(conf, 3), "grammar": gtext, "chosen": chosen, "ok": ok,
                "expected": want, "got": got, "correct": bool(ok and chosen and got == want)}


class _ListHandler(logging.Handler):
    """Keeps the listener's own log lines for the clip being scored."""

    def __init__(self, sink: list[str]) -> None:
        super().__init__(logging.INFO); self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append(record.getMessage())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def evaluate(p: Pipeline, folder: Path) -> tuple[list[dict[str, Any]], list[float]]:
    clips = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["clips"]
    silence = next((read_wav(folder / c["file"]) for c in clips if c["kind"] == "silence"), None)
    bg = quiet_background(silence, 0.6)
    rows: list[dict[str, Any]] = []
    logs: list[str] = []
    handler = _ListHandler(logs); logger = logging.getLogger("jarvis"); logger.addHandler(handler)
    for c in clips:
        if c["kind"] == "silence": continue
        logs.clear()
        audio = read_wav(folder / c["file"]); row: dict[str, Any] = dict(c)
        row["speaker"] = p.speaker_score(VP.trim_silence(audio))
        if c["kind"] in ("wake", "wake_command"):
            w = p.wake(audio, bg); ring = w.pop("ring", None); row["wake"] = w
            if c["kind"] == "wake_command":
                if w["triggered"] and ring is not None:
                    # what the listener buffered since the wake word, then the rest of the clip as it keeps arriving
                    tail = ring[-1][0] + len(ring[-1][1]); full = np.concatenate([bg, audio, bg, bg])
                    more = [full[i:i + CHUNK] for i in range(tail, len(full) - CHUNK + 1, CHUNK)]
                    row["command"] = p.command(frames_after(ring, int(w["frm"])) + more, reference_text(c), float(w["skip"]))
                else:
                    row["command"] = {"correct": False, "chosen": "", "free": "", "why": "no wake"}
        else:
            x = np.concatenate([bg, audio, bg])
            row["command"] = p.command([x[i:i + CHUNK] for i in range(0, len(x) - CHUNK + 1, CHUNK)], reference_text(c))
        row["log"] = [m for m in logs if m.startswith(("wake verify", "capture:", "grammar command", "dropped", "local intent", "quick command", "fuzzy"))]
        rows.append(row); print(line(row), flush=True)
    logger.removeHandler(handler)
    p.background_triggers = p.background_wakes(silence, bg) if silence is not None else 0
    impostor = [s for s in (p.speaker_score(w) for w in background_windows(silence, float(p.speaker.setting("speaker_window_s")))) if s is not None]
    return rows, impostor


def training_clips(rows: list[dict[str, Any]]) -> list[str]:
    """Every other command-like clip that the owner said clearly: the training half of a split (the rest stays held out)."""
    good = [r["file"] for r in rows if r["kind"] in ("command", "wake_command") and r.get("peak", 0) >= 0.05]
    return good[::2]


def enroll(p: Pipeline, folder: Path, rows: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    files = training_clips(rows)
    clips = [VP.trim_silence(read_wav(folder / f)) for f in files]
    embeddings = [p.speaker.embed(c) for c in clips if len(c) >= SR // 2]
    profile = VP.make_profile(embeddings); profile["source"] = "calibration %s, %d clips" % (folder.name, len(embeddings))
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(profile), encoding="utf-8")
    return {"path": str(out), "clips": len(embeddings), "threshold": profile["threshold"], "training_files": files}


def line(r: dict[str, Any]) -> str:
    parts = ["%-13s %-42s" % (r["kind"], reference_text(r)[:42])]
    if "wake" in r:
        w = r["wake"]; parts.append("wake %s conf=%s oww=%.2f verify=%s spk=%s" % ("OK " if w["triggered"] else "NO ", w["conf"], w["oww"], w["verify"], w["speaker_ok"]))
    if "command" in r:
        c = r["command"]; parts.append("cmd %s %r" % ("OK " if c["correct"] else "MISS", c.get("chosen") or c.get("free")))
    if r.get("speaker") is not None: parts.append("score=%.3f" % r["speaker"])
    return " | ".join(parts)


def newest(home: Path) -> Path:
    return sorted(d for d in (home / "calibration").iterdir() if (d / "manifest.json").exists())[-1]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--home", required=True, type=Path); ap.add_argument("--dir", type=Path)
    ap.add_argument("--set", action="append", default=[], help="config override key=json")
    ap.add_argument("--label", default="current")
    ap.add_argument("--enroll", type=Path, help="write a candidate voice profile from the even-numbered clean clips here")
    a = ap.parse_args(argv)
    logging.getLogger("jarvis").setLevel(logging.INFO); logging.getLogger("jarvis").propagate = False
    folder = a.dir or newest(a.home)
    cfg = dict(settings.config_store(a.home).load()); cfg.update(parse_overrides(a.set))
    p = Pipeline.load(a.home, cfg)
    rows, impostor = evaluate(p, folder)
    summary = summarize(rows, impostor); summary["background_wake_triggers"] = p.background_triggers
    if a.enroll: summary["enrolled_profile"] = enroll(p, folder, rows, a.enroll)
    owner = [r["wake"]["speaker_score"] for r in rows if "wake" in r and r["wake"].get("speaker_score") is not None]
    summary["suggested_speaker_threshold"] = suggest_speaker_threshold(owner, impostor)
    (folder / ("eval-%s.json" % a.label)).write_text(json.dumps({"overrides": parse_overrides(a.set), "summary": summary, "rows": rows},
                                                                ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
