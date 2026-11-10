"""Offline ASR comparison for the command set: free Vosk, grammar-limited Vosk, faster-whisper.

    python scripts/eval_asr.py --home <JARVIS_HOME> --out <dir> synth      # Silero voices -> WAV
    python scripts/eval_asr.py --home <JARVIS_HOME> --out <dir> vosk       # free vs grammar
    python scripts/eval_asr.py --home <JARVIS_HOME> --out <dir> whisper --model base

Clips are synthetic (several Silero voices, light noise), so the numbers compare recognizers
with each other, not with a real microphone. Accuracy for commands means the recognized text
routes to the same local command as the reference phrase. For free questions the grammar
recognizer must stay silent ([unk]); anything else would have become a wrong command.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import jarvis_commands as Q  # noqa: E402

SR = 16000
COMMANDS = ["объясни эту ошибку", "статус сервера роутер", "запусти тесты проекта голосовой помощник",
            "сколько осталось до нормы белка", "добавь двести грамм творога", "сделай скриншот", "отмени таймер",
            "режим фокуса", "закрой окно", "прочитай буфер", "выключи звук", "включи звук", "повтори",
            "отмени выключение", "сколько свободно на диске", "создай ветку для задачи авторизация",
            "открой пул реквест", "запусти миграции", "кратко перескажи буфер", "переведи буфер на английский",
            "что в гите проекта голосовой помощник", "проверь серверы", "режим тренировки", "сколько осталось калорий"]
FREE = ["какая погода завтра в париже", "почему небо голубое", "сколько стоит биткоин сегодня",
        "расскажи анекдот про программистов", "как перевести слово ответственность на английский",
        "что нового в мире искусственного интеллекта", "найди рецепт сырников", "во сколько завтра первая встреча",
        "почему падает сборка на гитхабе", "напомни что я обещал сделать на этой неделе"]
VOICES = ["eugene", "aidar", "baya", "xenia"]
CFG = {"food_local_enabled": True}


def route(text: str) -> Optional[str]:
    a = Q.match(text, CFG)
    return None if a is None else json.dumps({k: v for k, v in a.items() if k not in ("name",)}, ensure_ascii=False, sort_keys=True)


def norm(t: str) -> str:
    return " ".join(Q.norm(t).replace(",", " ").replace(".", " ").split())


def write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def synth(home: Path, out: Path) -> None:
    import torch
    tts = torch.package.PackageImporter(str(home / "models" / "silero" / "v5_6_ru.pt")).load_pickle("tts_models", "model")
    rng = np.random.default_rng(7); rows = []
    for group, phrases in (("command", COMMANDS), ("free", FREE)):
        for i, text in enumerate(phrases):
            for voice in VOICES:
                a = tts.apply_tts(text=text, speaker=voice, sample_rate=48000).numpy().astype(np.float32)[::3]
                a = np.concatenate([np.zeros(4000, np.float32), a * 0.6, np.zeros(8000, np.float32)])
                a = a + rng.normal(0, 0.004, len(a)).astype(np.float32)
                name = "%s_%02d_%s.wav" % (group, i, voice); write_wav(out / name, a)
                rows.append({"file": name, "group": group, "text": text, "voice": voice, "seconds": round(len(a) / SR, 2)})
    (out / "clips.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("clips", len(rows))


def _decode(rec, audio: np.ndarray) -> Dict[str, object]:
    b = (audio * 32767).astype(np.int16).tobytes(); words = []; t0 = time.perf_counter()
    for i in range(0, len(b), 3200):  # 100 ms chunks, like the listener
        if rec.AcceptWaveform(b[i:i + 3200]):
            words += json.loads(rec.Result()).get("result", [])
    t_last = time.perf_counter()
    words += json.loads(rec.FinalResult()).get("result", [])
    t_end = time.perf_counter()
    words = [w for w in words if w["word"] != "[unk]"]
    return {"text": " ".join(w["word"] for w in words), "conf": round(sum(w["conf"] for w in words) / len(words), 3) if words else 0.0,
            "decode_s": round(t_end - t0, 4), "final_s": round(t_end - t_last, 4)}


def eval_vosk(home: Path, out: Path) -> None:
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    model = Model(str(home / "models" / "vosk-model-small-ru-0.22"))
    grammar = json.dumps(sorted(set(norm(p) for p in Q.PHRASES + COMMANDS)) + ["[unk]"], ensure_ascii=False)
    rows = json.loads((out / "clips.json").read_text(encoding="utf-8")); res = []
    for r in rows:
        a = read_wav(out / r["file"])
        free = KaldiRecognizer(model, SR); free.SetWords(True)
        gram = KaldiRecognizer(model, SR, grammar); gram.SetWords(True)
        res.append(dict(r, free=_decode(free, a), grammar=_decode(gram, a)))
    (out / "vosk.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    report(res, ("free", "grammar"))


def eval_whisper(out: Path, size: str) -> None:
    from faster_whisper import WhisperModel
    t0 = time.perf_counter(); m = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4)
    load = time.perf_counter() - t0
    rows = json.loads((out / "clips.json").read_text(encoding="utf-8")); res = []
    for r in rows:
        a = read_wav(out / r["file"]); t0 = time.perf_counter()
        segs, _ = m.transcribe(a, language="ru", beam_size=1, vad_filter=False, condition_on_previous_text=False)
        text = " ".join(s.text for s in segs)
        dt = time.perf_counter() - t0
        res.append(dict(r, whisper={"text": norm(text), "conf": 1.0, "decode_s": round(dt, 3), "final_s": round(dt, 3)}))
    (out / ("whisper_%s.json" % size)).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("whisper %s load_s=%.1f rss_mb=%s" % (size, load, rss_mb()))
    report(res, ("whisper",))


def rss_mb() -> Optional[int]:
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        c = PMC(); c.cb = ctypes.sizeof(c)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return int(c.PagefileUsage / 2 ** 20)
    except Exception:
        return None


def report(res: List[Dict[str, object]], engines) -> None:
    for e in engines:
        cmd = [r for r in res if r["group"] == "command"]; free = [r for r in res if r["group"] == "free"]
        routed = sum(route(r[e]["text"]) == route(r["text"]) for r in cmd)
        exact = sum(norm(r[e]["text"]) == norm(r["text"]) for r in cmd)
        free_exact = sum(norm(r[e]["text"]) == norm(r["text"]) for r in free)
        false_cmd = sum(route(r[e]["text"]) is not None for r in free)
        audio = sum(r["seconds"] for r in res); dec = sum(r[e]["decode_s"] for r in res)
        fin = sorted(r[e]["final_s"] for r in res)
        print("%-8s commands routed %d/%d exact %d/%d | free exact %d/%d false-command %d/%d | RTF %.3f final p50 %.0f ms p95 %.0f ms"
              % (e, routed, len(cmd), exact, len(cmd), free_exact, len(free), false_cmd, len(free), dec / audio,
                 fin[len(fin) // 2] * 1000, fin[int(len(fin) * .95)] * 1000))
        for r in cmd:
            if route(r[e]["text"]) != route(r["text"]):
                print("   miss %-45s %-7s -> %r (%.2f)" % (r["text"], r["voice"], r[e]["text"], r[e]["conf"]))


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", required=True, type=Path); ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("stage", choices=("synth", "vosk", "whisper")); ap.add_argument("--model", default="base")
    a = ap.parse_args(argv); a.out.mkdir(parents=True, exist_ok=True)
    {"synth": lambda: synth(a.home, a.out), "vosk": lambda: eval_vosk(a.home, a.out), "whisper": lambda: eval_whisper(a.out, a.model)}[a.stage]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
