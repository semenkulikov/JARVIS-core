"""Record the owner's real voice for tuning wake, commands and speaker checks (about 6 minutes).

    python scripts/calibrate_voice.py --home C:\\Jarvis\\voice

A running Jarvis is paused while you record (it starts again afterwards; --keep-listener skips
that), so none of the commands below is executed. Each clip is shown with a short countdown and
saved as 16 kHz mono WAV in <home>/calibration/<timestamp>/ with manifest.json. Before each
clip: Enter records, r redoes the previous clip, s skips, q stops (what is recorded is kept).
The recordings stay on this machine; scripts/eval_calibration.py scores them.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from jarvis.adapters.audio import SR, clip_level, pick_device  # noqa: E402
from jarvis.commands import catalog  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enroll_speaker import listener_paused  # noqa: E402

WAKE_HINTS = (
    "обычным голосом, сидя у ноутбука", "обычным голосом, сидя у ноутбука", "обычным голосом, сидя у ноутбука",
    "тихо, как будто рядом кто-то спит", "тихо, отвернувшись от ноутбука",
    "из другого конца комнаты, обычным голосом", "из другого конца комнаты, погромче",
    "громко и чётко", "быстро, на ходу", "протяжно: «Джаарвис»",
)
# Phrases that failed on the synthetic voice or matter most; the rest comes from the command catalogue.
PRIORITY = (
    "утренний брифинг", "чё ещё осталось", "выруби экран", "когда тренировка", "перескажи все задачи",
    "что ты умеешь", "спящий режим на десять минут", "объясни эту ошибку", "открой пул реквест",
)
WAKE_COMMANDS = (
    "что ты умеешь", "утренний брифинг", "который час", "чё ещё осталось", "поставь таймер на пять минут",
    "выруби экран", "когда тренировка", "сколько заряда", "перескажи все задачи", "стоп",
)
MAX_COMMANDS = 40


@dataclass(frozen=True)
class Item:
    kind: str        # wake | command | wake_command | silence
    text: str        # what to say ("" for silence)
    hint: str
    seconds: float


def command_phrases(limit: int = MAX_COMMANDS) -> list[str]:
    """The priority phrases, then the first example of every catalogue command, without repeats."""
    out: list[str] = []
    for phrase in list(PRIORITY) + [c.examples[0] for c in catalog.COMMANDS if c.examples]:
        if phrase not in out: out.append(phrase)
    return out[:limit]


def build_plan() -> list[Item]:
    plan = [Item("wake", "Джарвис", hint, 2.5) for hint in WAKE_HINTS]
    plan += [Item("command", p, "обычным голосом, без «Джарвис»", 3.5) for p in command_phrases()]
    plan += [Item("wake_command", "Джарвис … " + p, "«Джарвис», естественная пауза, затем команда", 5.0) for p in WAKE_COMMANDS]
    plan.append(Item("silence", "", "молчите 30 секунд: обычный фон комнаты (можно печатать)", 30.0))
    return plan


def slug(item: Item, index: int) -> str:
    words = "".join(ch if ch.isalnum() else "_" for ch in item.text.lower()).strip("_")
    return "%02d_%s_%s.wav" % (index, item.kind, "_".join(w for w in words.split("_") if w)[:40] or "room")


def write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def level_note(peak: float) -> str:
    if peak < 0.02: return " — почти не слышно: проверьте микрофон"
    if peak < 0.06: return " — тихо"
    if peak > 0.98: return " — перегруз"
    return ""


def run(plan: list[Item], out: Path, record: Callable[[float], np.ndarray], ask: Callable[[str], str] = input,
        say: Callable[[str], None] = print, countdown: Callable[[], None] = lambda: None) -> list[dict[str, Any]]:
    """Walk the plan; returns the manifest rows of the clips that were kept."""
    out.mkdir(parents=True, exist_ok=True)
    rows: dict[int, dict[str, Any]] = {}
    i = 0; last: Optional[int] = None
    while i < len(plan):
        item = plan[i]
        say("\n[%d/%d] %s" % (i + 1, len(plan), item.hint))
        if item.text: say("    >>> %s <<<" % item.text)
        key = ask("    Enter — записать (%.0f с), r — переписать прошлую, s — пропустить, q — выйти: " % item.seconds).strip().lower()
        if key == "q": break
        if key == "s": i += 1; continue
        if key == "r" and last is not None: i = last; continue
        countdown()
        audio = record(item.seconds)
        name = slug(item, i + 1); write_wav(out / name, audio)
        peak, rms = clip_level(audio)
        rows[i] = dict(asdict(item), file=name, peak=round(peak, 4), rms=round(rms, 5))
        say("    записано: %s, пик %.3f%s" % (name, peak, level_note(peak)))
        last = i; i += 1
    kept = [rows[k] for k in sorted(rows)]
    (out / "manifest.json").write_text(json.dumps({"created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                                                   "sample_rate": SR, "clips": kept}, ensure_ascii=False, indent=1), encoding="utf-8")
    return kept


def mic_recorder(cfg: dict[str, Any]) -> tuple[Callable[[float], np.ndarray], str]:
    """Record from the same microphone the listener picks."""
    import sounddevice as sd
    dev = pick_device(sd, cfg)
    name = str(sd.query_devices(dev)["name"] if dev is not None else sd.query_devices(kind="input")["name"])

    def record(seconds: float) -> np.ndarray:
        a = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="float32", device=dev); sd.wait()
        return np.asarray(a[:, 0], dtype=np.float32)
    return record, name


def countdown() -> None:
    for n in ("3", "2", "1"):
        print("    " + n, end="", flush=True); time.sleep(0.4)
    print("   ГОВОРИТЕ", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--home", required=True, type=Path)
    ap.add_argument("--keep-listener", action="store_true", help="do not pause a running Jarvis while recording")
    a = ap.parse_args(argv)
    cfg: dict[str, Any] = {}
    try: cfg = json.loads((a.home / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError): pass
    record, mic = mic_recorder(cfg)
    plan = build_plan()
    out = a.home / "calibration" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    print("Микрофон: %s. Клипов: %d, запись около %.0f мин." % (mic, len(plan), sum(i.seconds for i in plan) / 60 + 2))
    if a.keep_listener: kept = run(plan, out, record, countdown=countdown)
    else:
        with listener_paused(a.home): kept = run(plan, out, record, countdown=countdown)
    print("\nГотово: %d клипов в %s" % (len(kept), out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
