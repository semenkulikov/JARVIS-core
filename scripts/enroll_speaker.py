"""Enroll the owner's voice for optional speaker verification (does not enable it).

    python scripts/enroll_speaker.py --home C:\\Jarvis\\voice --download
    python scripts/enroll_speaker.py --home C:\\Jarvis\\voice --wav a.wav --wav b.wav

Records a few phrases from the default microphone (or reads 16 kHz mono WAV files),
writes <home>/speaker/profile.json with a suggested threshold and prints how to turn the
check on: "speaker_verify_enabled": true in config.json. Nothing leaves the machine
except the one-time model download from Hugging Face (SHA-256 verified).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path
from typing import List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import jarvis_speaker as S  # noqa: E402

PHRASES = [
    "Джарвис, какой у меня статус по задачам на сегодня?",
    "Хей, Джарвис, поставь таймер на двадцать пять минут.",
    "Джарвис, сколько белка я сегодня съел?",
    "Джарвис, открой браузер и проверь почту.",
    "Хей, Джарвис, что у меня в календаре на завтра?",
    "Джарвис, спящий режим на один час.",
    "Джарвис, повтори, пожалуйста, последний ответ.",
    "Хей, Джарвис, сделай скриншот экрана.",
]


def download_model(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".part")
    os.close(fd)
    print("downloading", S.MODEL_URL)
    with urllib.request.urlopen(S.MODEL_URL, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    digest = S.file_sha256(tmp)
    if digest != S.MODEL_SHA256:
        os.remove(tmp)
        raise SystemExit("model checksum mismatch: %s" % digest)
    os.replace(tmp, target)
    print("model ok:", target)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != S.SR or w.getsampwidth() != 2:
            raise SystemExit("%s: need 16 kHz 16-bit WAV" % path)
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        return a[:: w.getnchannels()]


def record(seconds: float, count: int) -> List[np.ndarray]:
    import sounddevice as sd
    clips = []
    for i, phrase in enumerate(PHRASES[:count], 1):
        input("\n[%d/%d] Нажмите Enter и прочитайте вслух обычным голосом:\n    %s\n" % (i, count, phrase))
        a = sd.rec(int(seconds * S.SR), samplerate=S.SR, channels=1, dtype="float32")
        sd.wait()
        clips.append(a[:, 0])
        print("    записано %.1f c" % seconds)
    return clips


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", required=True, type=Path)
    ap.add_argument("--wav", action="append", type=Path, default=[])
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--download", action="store_true", help="fetch the 26.5 MB model if missing")
    a = ap.parse_args(argv)
    cfg = dict(S.DEFAULTS)
    try:
        cfg.update(json.loads((a.home / "config.json").read_text(encoding="utf-8-sig")))
    except OSError:
        pass
    verifier = S.SpeakerVerifier(a.home, cfg)
    model = verifier._path("speaker_model")
    if not model.exists():
        if not a.download:
            raise SystemExit("model missing: %s (run with --download)" % model)
        download_model(model)
    clips = [read_wav(p) for p in a.wav] if a.wav else record(a.seconds, max(3, min(a.count, len(PHRASES))))
    clips = [S.trim_silence(c) for c in clips]
    clips = [c for c in clips if len(c) >= S.SR]
    if len(clips) < 3:
        raise SystemExit("need at least 3 clips with >= 1 s of speech")
    embeddings = [verifier.embed(c) for c in clips]
    profile = S.make_profile(embeddings)
    path = verifier._path("speaker_profile")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.%d.bak" % int(time.time())))
    path.write_text(json.dumps(profile), encoding="utf-8")
    c = np.asarray(profile["centroid"], dtype=np.float32)
    print("\nprofile: %s  clips=%d  threshold=%.3f" % (path, len(clips), profile["threshold"]))
    print("owner scores:", ", ".join("%.3f" % S.cosine(e, c) for e in embeddings))
    print('Verification stays OFF. To enable add "speaker_verify_enabled": true to config.json.')
    return 0


if __name__ == "__main__":
    sys.exit(main())
