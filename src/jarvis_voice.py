# Jarvis voice assistant 3.14.0
import os
for _k, _v in {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "1"}.items(): os.environ.setdefault(_k, _v)
import sys, json, time, uuid, queue, threading, logging, subprocess, datetime, re, tempfile, collections, difflib, shlex, urllib.parse
from logging.handlers import RotatingFileHandler
import ctypes
from ctypes import wintypes
import numpy as np
import sounddevice as sd

import jarvis_paths as PATHS
BASE = str(PATHS.HOME)
LOGDIR = str(PATHS.log_dir())
os.makedirs(LOGDIR, exist_ok=True)
OUTBOX = os.path.join(BASE, "outbox"); DONE = os.path.join(OUTBOX, "done")
os.makedirs(DONE, exist_ok=True); os.makedirs(os.path.join(BASE, "cache"), exist_ok=True)
TEST_TRIGGER = os.path.join(BASE, "test_trigger")
STOP_FILE = os.path.join(BASE, "stop")

log = logging.getLogger("jarvis")
log.setLevel(logging.INFO)
if not log.handlers:
    h = RotatingFileHandler(os.path.join(LOGDIR, "jarvis_voice.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)

import jarvis_text as JT
import laptop as LP
import random
import jarvis_commands as QUICK
import jarvis_proactive as PROACTIVE
import jarvis_credentials as CREDS
import jarvis_runtime as RUNTIME
import jarvis_gate as GATE
import jarvis_sleep as SLEEP
CMDS = None
def command_controller():
    global CMDS
    if CMDS is None: CMDS = QUICK.Controller(BASE)
    return CMDS

import jarvis_speed as SPEED
OUTBOX_SIGNAL = SPEED.OutboxSignal(OUTBOX)

def perf(event, **meta):
    tr = STATE.get("trace")
    if tr is not None: tr.mark(event, **meta)


DEFAULT_ALIASES = [
    {"name": "status", "phrases": ["статус", "статус по задачам", "отчёт", "доклад", "сводка", "что по задачам"], "action": "status"},
    {"name": "food", "phrases": ["сколько белка", "сколько калорий", "что по еде", "что по питанию"], "action": "cache_field", "field": "food"},
    {"name": "today", "phrases": ["что сегодня", "какие планы", "планы на сегодня"], "action": "cache_field", "field": "today"},
    {"name": "deploy", "phrases": ["как деплой", "что по проектам", "что с деплоем"], "action": "cache_field", "field": "deploy"},
    {"name": "time", "phrases": ["который час", "время", "сколько времени"], "action": "time"},
    {"name": "stop", "phrases": ["заткнись", "замолкни", "замолчи", "шадап", "шат ап", "шатап", "хватит", "стоп", "тихо", "помолчи", "умолкни", "довольно", "отставить", "отмена"], "action": "stop"},
    {"name": "vol_up", "phrases": ["громче", "погромче", "сделай громче"], "action": "key", "key": "vol_up", "times": 5, "extra_words": 1},
    {"name": "vol_down", "phrases": ["тише", "потише", "сделай тише"], "action": "key", "key": "vol_down", "times": 5, "extra_words": 1},
    {"name": "mute", "phrases": ["без звука", "выключи звук", "верни звук", "включи звук"], "action": "key", "key": "mute", "times": 1, "extra_words": 1},
    {"name": "play", "phrases": ["пауза", "продолжи", "продолжай", "играй"], "action": "key", "key": "play", "times": 1, "silent": True, "extra_words": 0},
    {"name": "next", "phrases": ["дальше", "следующий", "следующая"], "action": "key", "key": "next", "times": 1, "silent": True, "extra_words": 0},
    {"name": "prev", "phrases": ["назад", "предыдущий", "предыдущая"], "action": "key", "key": "prev", "times": 1, "silent": True, "extra_words": 0},
    {"name": "monitor_off", "phrases": ["выключи экран", "погаси экран", "выключи монитор"], "action": "monitor_off"},
    {"name": "timer_cancel", "phrases": ["отмени таймер", "отключи таймер", "убери таймер"], "action": "timer_cancel"},
    {"name": "timer", "phrases": ["таймер", "поставь таймер"], "action": "timer", "extra_words": 5},
    {"name": "battery", "phrases": ["заряд", "сколько заряда", "батарея"], "action": "battery", "extra_words": 1},
    {"name": "temperature", "phrases": ["температура", "какая температура"], "action": "temperature", "extra_words": 1},
    {"name": "browser", "phrases": ["открой браузер", "браузер"], "action": "open", "target": "https://www.google.com"},
    {"name": "youtube", "phrases": ["открой ютуб"], "action": "open", "target": "https://www.youtube.com"},
    {"name": "github", "phrases": ["открой гитхаб", "открой гит хаб"], "action": "open_github"},
    {"name": "project", "phrases": ["открой проект"], "action": "open_project", "extra_words": 6},
    {"name": "cursor", "phrases": ["открой курсор"], "action": "open", "target": "%LOCALAPPDATA%\\Programs\\cursor\\Cursor.exe"},
    {"name": "telegram", "phrases": ["открой телеграм", "открой телеграмм"], "action": "open", "target": "%APPDATA%\\Telegram Desktop\\Telegram.exe"},
    {"name": "lock", "phrases": ["заблокируй экран", "заблокируй компьютер", "блокировка"], "action": "lock", "reply": "Блокирую, сэр."},
    {"name": "workout", "phrases": ["когда тренировка", "тренировка"], "action": "workout"},
]

# Local conversation: whole short utterances only, never a substring in a request.
SMALLTALK = [
    ("morning", ["доброе утро", "с добрым утром", "доброго утра"], ["Доброе утро, сэр. Рад вас слышать.", "С добрым утром, сэр. Я к вашим услугам.", "Доброе утро, сэр. Хорошего начала дня."]),
    ("day", ["добрый день", "доброго дня"], ["Добрый день, сэр. Рад вас слышать.", "Доброго дня, сэр. Всегда к вашим услугам."]),
    ("evening", ["добрый вечер", "доброго вечера"], ["Добрый вечер, сэр. Рад вас слышать.", "Добрый вечер, сэр. Надеюсь, день прошёл хорошо."]),
    ("night", ["спокойной ночи", "доброй ночи", "я спать", "иду спать"], ["Спокойной ночи, сэр. Приятных снов.", "Доброй ночи, сэр. Хорошего отдыха."]),
    ("hello", ["привет", "приветик", "здравствуй", "здравствуйте", "здорово", "салют", "хай"], ["Рад вас слышать, сэр.", "Здравствуйте, сэр. Я к вашим услугам.", "{greeting}, сэр. Рад вас слышать."]),
    ("how", ["как дела", "как ты", "как твои дела", "как поживаешь", "как настроение", "как сам"], ["Всё в порядке, сэр. Рад нашей беседе.", "Прекрасно, сэр. Особенно когда вы на связи.", "В рабочем настроении, сэр. А вы как?"]),
    ("thanks", ["спасибо", "благодарю", "спасибочки", "спасибо тебе", "большое спасибо"], ["Всегда пожалуйста, сэр.", "Рад помочь, сэр.", "К вашим услугам, сэр."]),
    ("praise", ["молодец", "умница", "красавчик", "отличная работа", "хорошая работа", "ты лучший"], ["Благодарю, сэр. Стараюсь для вас.", "Приятно слышать, сэр.", "Рад, что вы довольны, сэр."]),
    ("here", ["ты тут", "ты здесь", "ты на месте", "ты на связи", "слышишь меня", "ты меня слышишь"], ["Да, сэр. Я здесь и слушаю.", "На связи, сэр.", "Здесь, сэр. К вашим услугам."]),
    ("identity", ["кто ты", "как тебя зовут", "ты кто"], ["Джарвис, сэр. Ваш голосовой помощник.", "Ваш Джарвис, сэр. Всегда к вашим услугам."]),
    ("bye", ["пока", "до свидания", "до встречи", "увидимся"], ["До встречи, сэр. Я остаюсь на связи.", "Всего доброго, сэр.", "До свидания, сэр. Хорошего {daypart}."]),
    ("okay", ["окей", "хорошо", "ладно", "понятно", "ясно", "все хорошо", "все нормально", "да да да", "да да", "да окей"], ["Хорошо, сэр.", "Понял вас, сэр.", "Как скажете, сэр."]),
    ("done", ["все", "это все", "на этом все", "все спасибо", "пока все", "больше ничего"], ["Хорошо, сэр.", "Как скажете, сэр.", "Понял, сэр. Я на связи."]),
    ("mood", ["у меня все хорошо", "у меня все отлично", "нормально", "все отлично"], ["Рад это слышать, сэр.", "Прекрасно, сэр. Пусть так и продолжается."]),
]
SMALLTALK_ALIASES = [{"name": "chat_" + k, "phrases": ph, "action": "smalltalk", "replies": r, "extra_words": 0} for k, ph, r in SMALLTALK]

def smalltalk_reply(al):
    hour = datetime.datetime.now().hour
    greeting = "Доброе утро" if 5 <= hour < 12 else "Добрый день" if 12 <= hour < 18 else "Добрый вечер" if 18 <= hour < 23 else "Доброй ночи"
    daypart = "дня" if 5 <= hour < 18 else "вечера" if 18 <= hour < 23 else "отдыха"
    text = pick({al["name"]: al["replies"]}, al["name"])
    return text.format(greeting=greeting, daypart=daypart)

DEFAULTS = {
    "webhook_url": "",
    "webhook_auth_header": "",
    "tts_engine": "silero", "silero_model": "v5_6_ru", "silero_speaker": "eugene", "silero_rate": "fast",
    "vosktts_speaker": 3, "piper_voice": "ruslan", "piper_length_scale": 0.85,
    "tts_chunk_chars": 170, "tts_gap_s": 0.08,
    "fast_ack": "Сейчас, сэр.", "outbox_watch_enabled": True, "outbox_event_batch_s": 0.02, "outbox_watch_rescan_s": 1.0, "outbox_poll_s": 0.12,
    "intent_fuzzy_enabled": True, "intent_fuzzy_threshold": 88, "intent_fuzzy_margin": 7, "intent_max_words": 8,
    "time_preload_minutes": 3, "template_precache": True,
    "clipboard_max_chars": 8000, "clipboard_translate_target": "ru", "repeat_silero_rate": "slow",
    "shutdown_confirm_window_s": 10.0, "focus_minutes": 25, "workout_set_minutes": 3, "workout_water_minutes": 20,
    "workout_playlist_url": "", "timer_max_s": 604800,
    "stress_ruaccent": True, "ruaccent_model": "tiny2.1", "ruaccent_dictionary": False, "ruaccent_tiny_mode": True,
    "wake_word_enabled": True, "oww_enabled": True, "oww_threshold": 0.5, "barge_in_threshold": 0.6,
    "vosk_wake_min_conf": 0.80,
    "followup_enabled": True, "followup_window_s": 7.0, "followup_question_window_s": 10.0,
    "followup_echo_guard_s": 0.3, "followup_min_conf": 0.65, "followup_max_turns": 8,
    "wake_prebuffer_s": 1.6, "phrase_wait_s": 1.5, "phrase_silence_s": 0.95, "phrase_max_s": 10.0, "followup_listen_s": 7.0,
    "ack_command": ["Есть, сэр.", "Как прикажете, сэр.", "Будет сделано, сэр.", "Слушаюсь, сэр.", "Сию минуту, сэр.", "Уже делаю, сэр."],
    "ack_wake": ["Да, сэр?", "Слушаю, сэр.", "К вашим услугам, сэр.", "Чем могу помочь, сэр?"],
    "ack_free": ["Да, сэр.", "Слушаюсь, сэр.", "Секунду, сэр."],
    "ack_wait": ["Минуту, сэр, уточняю.", "Секунду, сэр.", "Почти готово, сэр."],
    "ack_not_understood": ["Простите, сэр, не расслышал. Повторите, пожалуйста."],
    "wait_filler_s": 12.0, "cache_stale_read_max_age_h": 3.0,
    "ack_status": ["Уточняю данные, сэр.", "Проверяю свежие данные, сэр."], "stop_phrases": ["заткнись", "замолкни", "замолчи", "шадап", "шат ап", "шатап", "хватит", "стоп", "тихо", "помолчи", "умолкни", "довольно", "отставить"], "ack_stop": ["Как скажете, сэр.", "Как прикажете.", "Умолкаю, сэр.", "Ладно, сэр."], "bargein_min_conf": 0.60, "min_conf": 0.55,
    "vosk_agc": True, "vosk_agc_max_gain": 12.0, "vosk_agc_target_peak": 0.6, "grammar_hint": True, "tts_threads": 3,
    "clap_enabled": True, "clap_min_peak": 0.2, "clap_ratio": 10.0, "clap_attack": 4.0, "clap_max_len_s": 0.15,
    "clap_decay": 0.25, "clap_gap_min_s": 0.12, "clap_gap_max_s": 0.9, "clap_quiet_s": 0.5, "clap_peak_similarity": 4.0,
    "clap_log_min_peak": 0.08, "clap_tail_s": 0.25, "clap_noise_rel": 0.35, "clap_noise_attack": 2.0,
    "cooldown_s": 1.0, "reply_timeout_s": 240, "server_notice_s": 90.0, "server_down_wait_s": 45.0, "server_down_ttl_s": 1800.0, "cache_max_age_h": 2.5,
    "workout_days": [], "workout_time": "12:00",
    "projects_dir": "",
    "level_log_interval_s": 300,
    "aliases": DEFAULT_ALIASES,
}

_CFG = {"m": None, "c": None}
DEFAULTS.update(PROACTIVE.DEFAULTS)
DEFAULTS.update({k: v for k, v in GATE.DEFAULTS.items() if k not in DEFAULTS})

def load_cfg():
    p = os.path.join(BASE, "config.json")
    try: m = os.path.getmtime(p)
    except Exception: m = None
    if _CFG["c"] is not None and _CFG["m"] == m: return _CFG["c"]
    cfg = dict(DEFAULTS)
    try:
        with open(p, encoding="utf-8-sig") as f: cfg.update(json.load(f))
        if _CFG["m"] is not None: log.info("config reloaded")
    except Exception as e:
        log.warning("config load failed: %s", e)
        if _CFG["c"] is not None: return _CFG["c"]
    # Portable defaults keep configuration knobs effective; no machine-specific migrations.
    if cfg.get("projects_dir"):
        LP.PROJ_DIR = os.path.expanduser(os.path.expandvars(cfg["projects_dir"]))
    cfg["webhook_auth_header"] = CREDS.webhook(cfg,BASE)
    cfg["aliases"] = [a for a in (cfg.get("aliases") or DEFAULT_ALIASES) if not a.get("name", "").startswith("chat_")] + SMALLTALK_ALIASES
    cfg["stress_dict"] = dict(dict(PROACTIVE.STRESS, **QUICK.STRESS), **(cfg.get("stress_dict") or {}))
    _CFG.update(m=m, c=cfg)
    return cfg

_LAST_PICK = {}
def pick(cfg, key):
    v = cfg.get(key) or DEFAULTS.get(key)
    if isinstance(v, str): return v
    v = [x for x in v if x] or [""]
    c = [x for x in v if x != _LAST_PICK.get(key)] or v
    r = random.choice(c); _LAST_PICK[key] = r; return r

def all_phrases(cfg):
    out = []
    for k in ("fast_ack", "ack_status", "ack_stop", "ack_command", "ack_wake", "ack_free", "ack_wait", "ack_not_understood"):
        v = cfg.get(k) or []
        out += [v] if isinstance(v, str) else list(v)
    for al in SMALLTALK_ALIASES:
        for r in al["replies"]:
            if "{" not in r: out.append(r)
            else:
                for greeting in ("Доброе утро", "Добрый день", "Добрый вечер", "Доброй ночи"):
                    for daypart in ("дня", "вечера", "отдыха"):
                        out.append(r.format(greeting=greeting, daypart=daypart))
    out += QUICK.CACHED_REPLIES + PROACTIVE.REPLIES
    return list(dict.fromkeys(out))

SR = 16000
CHUNK = 1280  # 80 ms, openWakeWord frame
audio_q = queue.Queue(maxsize=1000)
levels = {"max": 0.0, "sum": 0.0, "n": 0}
busy = threading.Event()        # a handler is running
speaking = threading.Event()
interrupt = threading.Event()   # wake word during busy -> stop speech/handler
STATE = {"capture": None, "model": None, "speaking_text": "", "rid": None, "stop_pending": False, "stop_ack_active": False, "followup_guard": False, "followup_eligible": False, "last_spoken": "", "last_spoken_end": 0.0, "speech_serial": 0, "trace": None, "last_reply": "", "last_reply_private": False, "reply_parts": [], "last_input_conf": 1.0, "last_input_end": None, "last_capture": None, "dropped": False}
CANCELLED = {}  # rid -> time
SLEEP_STATE = None
WAKE_FILE = os.path.join(BASE, SLEEP.WAKE_FILE)
SLEEP_END_PHRASE = "Я снова на связи, сэр."
def sleep_state():
    global SLEEP_STATE
    if SLEEP_STATE is None: SLEEP_STATE = SLEEP.SleepState(os.path.join(BASE, "cache", "sleep.json"))
    return SLEEP_STATE

def cb(indata, frames, t, status):
    try: audio_q.put_nowait(indata[:, 0].copy())
    except queue.Full: pass

# ================= TTS =================
_ENG = {}

def _cache_path(text, cfg, ext):
    import hashlib
    sig = json.dumps(["v3.8-stress2", JT.accent_state(), cfg.get("tts_engine"), cfg.get("silero_model"), cfg.get("stress_dict"), cfg.get("phrase_rewrites"),
                      cfg.get("fx"), cfg.get("silero_speaker"), cfg.get("silero_rate"), cfg.get("piper_voice"), text], ensure_ascii=False)
    cdir = os.path.join(BASE, "cache", "tts"); os.makedirs(cdir, exist_ok=True)
    return os.path.join(cdir, hashlib.md5(sig.encode("utf-8")).hexdigest() + ext)

def _silero_model(cfg):
    import torch
    if "silero_thr" not in _ENG:
        torch.set_num_threads(int(cfg.get("tts_threads", 3))); _ENG["silero_thr"] = 1
    mid = cfg.get("silero_model", "v5_6_ru")
    if _ENG.get("silero_id") != mid:
        p = os.path.join(BASE, "models", "silero", mid + ".pt")
        _ENG["silero"] = torch.package.PackageImporter(p).load_pickle("tts_models", "model"); _ENG["silero_id"] = mid
    return _ENG["silero"]

def _xml_escape(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

_SYN_LOCK = threading.Lock()

def synth_local(text, cfg):
    with _SYN_LOCK:
        return _synth_local(text, cfg)

def _synth_local(text, cfg):
    e = cfg.get("tts_engine", "silero")
    if e == "silero":
        m = _silero_model(cfg)
        kw = dict(speaker=cfg.get("silero_speaker", "eugene"), sample_rate=48000, put_accent=True, put_yo=True)
        if str(_ENG.get("silero_id", "")).startswith("v5"): kw.update(put_stress_homo=True, put_yo_homo=True)
        rate = cfg.get("silero_rate", "fast")
        def one(t):
            try:
                return m.apply_tts(ssml_text=f'<speak><prosody rate="{rate}">{_xml_escape(t)}</prosody></speak>', **kw)
            except Exception as ex:
                log.info("silero ssml failed (%s), plain text", type(ex).__name__ if cfg.get("private_tts") else ex)
                return m.apply_tts(text=t[:900], **kw)
        try:
            return one(text).numpy().astype(np.float32), 48000
        except Exception as ex:
            log.warning("silero failed on chunk (%s), per-sentence fallback", type(ex).__name__ if cfg.get("private_tts") else ex)
        outs = []
        for p in [x for x in re.split(r'(?<=[.!?…,;:])\s+', text) if x.strip()]:
            try: outs.append(one(p).numpy().astype(np.float32)); outs.append(np.zeros(int(48000 * 0.1), np.float32))
            except Exception as ex2: log.warning("silero skip part %r: %s", "[private clipboard text]" if cfg.get("private_tts") else p[:60], type(ex2).__name__)
        if not outs: raise RuntimeError("silero produced nothing")
        return np.concatenate(outs), 48000
    if e == "piper":
        from piper import PiperVoice, SynthesisConfig
        k = "piper:" + cfg.get("piper_voice", "ruslan")
        if k not in _ENG:
            _ENG[k] = PiperVoice.load(os.path.join(BASE, "models", "piper", f"ru_RU-{cfg.get('piper_voice','ruslan')}-medium.onnx"))
        v = _ENG[k]
        chunks = [c.audio_float_array for c in v.synthesize(text, syn_config=SynthesisConfig(length_scale=float(cfg.get("piper_length_scale", 0.85))))]
        return np.concatenate(chunks).astype(np.float32), v.config.sample_rate
    raise ValueError("unknown engine " + e)

def _wav_write(p, a, sr):
    import wave
    tmp = p + "." + uuid.uuid4().hex + ".tmp"
    try:
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp): os.remove(tmp)

def _wav_read(p):
    import wave
    with wave.open(p, "rb") as w:
        sr = w.getframerate(); d = w.readframes(w.getnframes())
    return np.frombuffer(d, dtype=np.int16).astype(np.float32) / 32767, sr

def split_text(text, limit=170):
    out = []
    for sent in re.split(r"(?<=[.!?…])\s+|\n+", text):
        sent = sent.strip()
        if not sent: continue
        if len(sent) <= limit: out.append(sent); continue
        cur = ""
        for piece in re.split(r"(?<=[,;:])\s+", sent):
            if cur and len(cur) + len(piece) + 1 > limit: out.append(cur); cur = piece
            else: cur = (cur + " " + piece).strip()
        if cur: out.append(cur)
    # Preserve sentence boundaries, especially the very first short sentence.
    # Bound even punctuation-free text by word boundaries.
    bounded = []
    for item in out:
        while len(item) > limit:
            cut = item.rfind(" ", 0, limit + 1)
            if cut <= 0: cut = limit
            bounded.append(item[:cut].strip()); item = item[cut:].strip()
        if item: bounded.append(item)
    return bounded

def get_audio(text, cfg):
    cp = _cache_path(text, cfg, ".wav")
    if os.path.exists(cp): return _wav_read(cp)
    norm = JT.normalize(text, cfg)
    a, sr = synth_local(norm, cfg)
    fx = cfg.get("fx", {"enabled": True})
    if fx.get("enabled", True):
        import jarvis_fx
        a, sr = jarvis_fx.apply(a, sr, fx)
    if len(text) <= 240 and not cfg.get("private_tts",False):
        try: _wav_write(cp, a, sr)
        except Exception: pass
    return a, sr

def precache(cfg):
    # Warm the first server ack before RUAccent has finished loading as well.
    try:
        get_audio(cfg.get("fast_ack", "Сейчас, сэр."), cfg)
        log.info("fast ack cache ready (initial)")
    except Exception as e: log.warning("fast ack warmup: %s", type(e).__name__)
    JT.init_accentizer(cfg, BASE)
    cfg = load_cfg(); pronunciation_audit = []
    for t in all_phrases(cfg) + ["Блокирую, сэр.", "Сэр, время вышло.", "Таймер отменён, сэр.", "Вебхук не настроен, сэр.", "Не получилось отправить запрос, сэр.",
              "Ответ не пришёл, сэр. Попробуйте ещё раз позже.", SERVER_DOWN_PHRASE, SERVER_SLOW_PHRASE, "Хорошо, сэр.", "Свежих данных нет, сэр, запрашиваю.", "Не нашёл приложение, сэр."]:
        pronunciation_audit.append({"text": t, "normalized": JT.normalize(t, cfg)})
        for att in range(10):
            try:
                for chunk in split_text(t, int(cfg.get("tts_chunk_chars",170))): get_audio(chunk, cfg)
                break
            except Exception as e: log.info("precache retry %s: %s", t, e); time.sleep(10)
    try:
        with open(os.path.join(BASE, "cache", "pronunciation_audit_v312.json"), "w", encoding="utf-8") as f:
            json.dump(pronunciation_audit, f, ensure_ascii=False, indent=2)
    except Exception as e: log.warning("pronunciation audit save failed: %s", type(e).__name__)
    log.info("precache done (%s, ruaccent=%s, audited_phrases=%d)", cfg.get("tts_engine"), JT.accent_state(), len(pronunciation_audit))
    if cfg.get("template_precache", True):
        templates = SPEED.template_phrases(cfg, JT)
        for phrase in templates:
            if os.path.exists(STOP_FILE): break
            # Do not queue background synthesis ahead of an active conversation.
            while busy.is_set() and not os.path.exists(STOP_FILE): time.sleep(0.1)
            if os.path.exists(STOP_FILE): break
            try: get_audio(phrase, cfg)
            except Exception as e: log.info("template cache skipped: %s", type(e).__name__)
        log.info("template precache done (%d bounded time/number sentences)", len(templates))
    trim_memory()

def trim_memory():
    import gc
    gc.collect()
    try:
        k = ctypes.windll.kernel32; k.GetCurrentProcess.restype = wintypes.HANDLE
        k.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_ssize_t, ctypes.c_ssize_t]
        k.SetProcessWorkingSetSize(k.GetCurrentProcess(), -1, -1)
    except Exception as e: log.info("trim failed: %s", e)
    log.info("memory: %s", mem_str())

def mem_str():
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("a", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in ("pws", "ws", "a1", "a2", "a3", "a4", "pf", "ppf", "priv")]
    k = ctypes.windll.kernel32; k.GetCurrentProcess.restype = wintypes.HANDLE
    k.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    p = PMC(); p.cb = ctypes.sizeof(p); k.K32GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(p), p.cb)
    return f"ws={p.ws >> 20}MB priv={p.priv >> 20}MB peak_ws={p.pws >> 20}MB"

def say(text, cfg, role="reply", private=False):
    """Speak text; synthesis of the next chunk overlaps playback. Returns False if interrupted/failed."""
    text = (text or "").strip()
    if not text: return True
    log.info("SAY start (%d chars): %s", len(text), "[private clipboard text]" if private else text[:800])
    if interrupt.is_set(): return False
    if private: cfg = dict(cfg, private_tts=True)
    chunks = split_text(text, int(cfg.get("tts_chunk_chars", 170)))
    q = queue.Queue(maxsize=2); err = []; cancelled = threading.Event()
    def enqueue(item):
        while not cancelled.is_set() and not interrupt.is_set():
            try: q.put(item, timeout=0.1); return True
            except queue.Full: pass
        return False
    def prod():
        for ch in chunks:
            if cancelled.is_set() or interrupt.is_set(): break
            try:
                item = get_audio(ch, cfg)
                if not enqueue(item): return
            except Exception as e: err.append(e); log.warning("tts chunk failed: %s", e)
        enqueue(None)
    threading.Thread(target=prod, daemon=True).start()
    speaking.set(); played = 0; t0 = time.time(); STATE["speaking_text"] = text.lower().replace("ё", "е")
    try:
        while True:
            if interrupt.is_set(): break
            try: item = q.get(timeout=0.1)
            except queue.Empty: continue
            if item is None or interrupt.is_set(): break
            a, sr = item
            if played == 0: log.info("tts first chunk ready in %.2fs", time.time() - t0)
            gap = np.zeros(int(sr * float(cfg.get("tts_gap_s", 0.08))), np.float32)
            perf("first_audio", audio_role=role)
            perf("first_ack_audio" if role == "ack" else "first_reply_audio")
            sd.play(np.concatenate([a, gap]), sr); sd.wait(); played += 1
        if interrupt.is_set():
            log.info("speech interrupted after %d/%d chunks", played, len(chunks)); return False
        if played == 0:
            log.warning("TTS produced nothing, chime instead: %s", "[private clipboard text]" if private else text[:200])
            try: beep()
            except Exception: pass
            return False
        STATE["last_spoken"] = text; STATE["last_spoken_end"] = time.monotonic()
        STATE["speech_serial"] += 1
        if role == "reply":
            STATE.setdefault("reply_parts", []).append(text)
            STATE["last_reply"] = " ".join(STATE["reply_parts"])
            STATE["last_reply_private"] = private or STATE.get("last_reply_private",False) if len(STATE["reply_parts"])>1 else bool(private)
        log.info("SPOKE(%d chunks): %s", played, "[private clipboard text]" if private else text[:200]); return True
    except Exception as e:
        log.warning("TTS/playback failed (%s)", e); return False
    finally:
        cancelled.set(); speaking.clear(); STATE["speaking_text"] = ""

def beep():
    t = np.linspace(0, 0.12, int(SR * 0.12), False)
    sd.play((0.25 * np.sin(2 * np.pi * 880 * t)).astype(np.float32), SR); sd.wait()

# ================= helpers =================
DAYS_ACC = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]

def quick_facts(cfg):
    now = datetime.datetime.now()
    s = f"Сейчас {JT.time_words(now.hour, now.minute)}."
    hh, mm = map(int, cfg["workout_time"].split(":"))
    days = cfg["workout_days"]
    if not days: return "Расписание тренировок ещё не настроено, сэр."
    if now.weekday() in days:
        tw = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < tw:
            m = int((tw - now).total_seconds() // 60); H, M = divmod(m, 60); parts = []
            if H: parts.append(f"{JT.num_ru(H)} {JT.plural(H,'час','часа','часов')}")
            if M or not H: parts.append(f"{JT.num_ru(M, 'f')} {JT.plural(M,'минута','минуты','минут')}")
            return s + " До тренировки " + " ".join(parts) + "."
        if (now - tw).total_seconds() < 5400: return s + " Тренировка идёт прямо сейчас."
    for i in range(1, 8):
        d = (now.weekday() + i) % 7
        if d in days:
            when = "завтра" if i == 1 else ("во " if d == 1 else "в ") + DAYS_ACC[d]
            pre = "Сегодня тренировки нет" if now.weekday() not in days else "Сегодняшняя тренировка уже была"
            return s + f" {pre}, следующая {when} в {JT.time_words(hh, mm)}."
    return s

def placeholder(cfg):
    u = str(cfg.get("webhook_url", "")).strip(); a = str(cfg.get("webhook_auth_header", ""))
    return urllib.parse.urlparse(u).scheme not in ("http", "https") or "PASTE" in u or "PASTE" in a

def clean_auth(h):
    h = str(h or "").replace("\ufeff", "").strip().strip('"').strip("'").strip()
    h = re.sub(r"^authorization\s*:\s*", "", h, flags=re.I).strip()
    return re.sub(r"[\r\n]", "", h)

def post(cfg, payload):
    import urllib.request
    url = str(cfg["webhook_url"]).replace("\ufeff", "").strip().strip('"').strip("'").strip()
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError("webhook_url_scheme")
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": clean_auth(cfg["webhook_auth_header"])})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status

def post_retry(cfg, payload, total=30, independent=False):
    t0 = time.time(); err = None
    while time.time() - t0 < total:
        if not independent and (interrupt.is_set() or payload.get("request_id") in CANCELLED): return None
        try: return post(cfg, payload)
        except Exception as e:
            err = e; log.warning("webhook attempt failed: %s code=%s", type(e).__name__, getattr(e, "code", None))
            if isinstance(e, ValueError): break
            code = getattr(e, "code", None)
            if code and 400 <= int(code) < 500 and int(code) != 429: break
            time.sleep(3)
    raise err

def call_webhook(rid, text, trigger, cfg, test, listener_ack="", kind="free", trace=None, extra_payload=None):
    payload = {"request_id": rid, "text": text, "trigger": trigger, "listener_ack": listener_ack, "kind": kind}
    allowed = {"task_text","clipboard_text","clipboard_truncated","context_source","target_language","food_text","confirmation_policy","local_date","timezone","reply_mode","outbox_file","presence_at","idle_seconds","expires_iso"}
    payload.update({k:v for k,v in (extra_payload or {}).items() if k in allowed})
    if placeholder(cfg):
        log.warning("webhook not configured; request_id=%s kind=%s",rid,kind)
        return False
    if trace is not None: trace.mark("post_start")
    try:
        t0 = time.monotonic(); log.info("webhook POST start rid=%s", rid)
        status = post_retry(cfg, payload,independent=True) if kind=="morning_briefing" else post_retry(cfg, payload)
        if trace is not None: trace.mark("post_done")
        log.info("webhook status %s (rid=%s) post_s=%.3f", status, rid, time.monotonic() - t0)
        return status is not None and 200 <= status < 300
    except Exception as e:
        log.error("webhook failed: %s code=%s", type(e).__name__, getattr(e, "code", None)); return False

def read_part(p):
    for _ in range(10):
        try:
            with open(p, encoding="utf-8-sig") as f: return f.read()
        except PermissionError: time.sleep(0.2)
    return ""

def move_done(p):
    try: os.replace(p, os.path.join(DONE, os.path.basename(p)))
    except Exception as e: log.warning("move failed %s: %s", p, e)

def say_reply(txt, cfg, private=False):
    t0 = time.time()
    while not say(txt, cfg, private=private):
        if interrupt.is_set() or time.time() - t0 > 30: return
        time.sleep(3)

def ready_part(p, allow_empty=False):
    """Avoid playing partially-written files, without a fixed 200 ms penalty."""
    try:
        a = os.stat(p)
        time.sleep(0.08)
        b = os.stat(p)
        return (a.st_size > 0 or allow_empty) and (a.st_size, a.st_mtime_ns) == (b.st_size, b.st_mtime_ns)
    except OSError: return False

def file_age(p):
    try: return max(0.0, time.time() - os.path.getmtime(p))
    except OSError: return 0.0

def log_outbox(p, rid, label, txt, t0):
    try: lag = max(0.0, time.time() - os.path.getmtime(p))
    except OSError: lag = -1
    log.info("outbox %s (%d chars) rid=%s wait_s=%.3f file_age_s=%.3f", label, len(txt), rid, time.time() - t0, lag)

def pure_wait_filler(text):
    t = " ".join(_norm_phrase(text))
    t = re.sub(r"\bсэр\b", "", t); t = " ".join(t.split())
    return bool(re.fullmatch(r"(?:(?:одну )?(?:минуту|секунду)(?: (?:уточняю|проверяю|посмотрю))?|(?:сейчас |уже )?(?:посмотрю|уточню|проверю|проверяю|смотрю|уточняю|запрашиваю)(?: (?:данные|календарь|задачи|статус))?|почти готово)", t))

SERVER_DOWN_PHRASE = "Сервер не отвечает, сэр. Локальные команды работают."
SERVER_SLOW_PHRASE = "Сервер пока молчит, сэр. Подожду ещё немного."
SERVER = {"down_since": None}

def server_recently_down(cfg, now=None):
    t = SERVER.get("down_since")
    return t is not None and ((now or time.time()) - t) < float(cfg.get("server_down_ttl_s", 1800))

def wait_replies(rid, cfg, listener_ack="", kind="free"):
    t0 = time.time(); n = 1; fillers = 0; STATE["rid"] = rid
    real_data_seen = False; server_seen = False; slow_noticed = False
    was_down = server_recently_down(cfg, t0)
    def speak_part(txt):
        nonlocal real_data_seen
        if GATE.is_silent_reply(txt):
            if txt.strip(): log.info("server asked for silence rid=%s", rid)
            return
        if listener_ack and not real_data_seen and pure_wait_filler(txt):
            log.info("skipped redundant server filler rid=%s: %r", rid, txt); return
        real_data_seen = True
        if kind.startswith("clipboard_"): say_reply(txt,cfg,private=True)
        else: say_reply(txt, cfg)
    final = os.path.join(OUTBOX, f"{rid}.txt")
    while time.time() - t0 < cfg["reply_timeout_s"]:
        OUTBOX_SIGNAL.clear()
        if not server_seen and (os.path.exists(final) or os.path.exists(os.path.join(OUTBOX, f"{rid}.{n}.txt"))):
            server_seen = True; SERVER["down_since"] = None
        el = time.time() - t0
        if not server_seen and was_down and el > float(cfg.get("server_down_wait_s", 45)):
            # Server already failed recently: do not hang for the full timeout again.
            CANCELLED[rid] = time.time(); SERVER["down_since"] = time.time()
            log.warning("server still silent rid=%s after %.0fs (down since earlier) -> local fallback", rid, el)
            say(SERVER_DOWN_PHRASE, cfg); return False
        if not server_seen and not was_down and not slow_noticed and el > float(cfg.get("server_notice_s", 90)):
            slow_noticed = True; log.info("server silent rid=%s after %.0fs -> notice", rid, el)
            say(SERVER_SLOW_PHRASE, cfg)
        # An initial acknowledgement is enough. No second "checking" announcement.
        if not listener_ack and not real_data_seen and fillers == 0 and time.time() - t0 > max(12.0, float(cfg.get("wait_filler_s", 12))) \
                and not os.path.exists(final) and not os.path.exists(os.path.join(OUTBOX, f"{rid}.{n}.txt")):
            fillers += 1; say("Ответ ещё готовится, сэр.", cfg)
        if interrupt.is_set():
            CANCELLED[rid] = time.time(); log.info("reply wait for %s abandoned (interrupted), rid cancelled", rid); return False
        part = os.path.join(OUTBOX, f"{rid}.{n}.txt")
        if os.path.exists(part) or os.path.exists(final): perf("first_server_file")
        if os.path.exists(part) and ready_part(part):
            perf("first_server_file")
            txt = read_part(part); log_outbox(part, rid, "part " + str(n), txt, t0)
            move_done(part); speak_part(txt); n += 1; continue
        if os.path.exists(final) and ready_part(final, allow_empty=real_data_seen or file_age(final) >= 0.6):
            perf("first_server_file")
            while os.path.exists(os.path.join(OUTBOX, f"{rid}.{n}.txt")):
                p = os.path.join(OUTBOX, f"{rid}.{n}.txt"); t = read_part(p); move_done(p); log.info("outbox part %d (%d chars)", n, len(t)); speak_part(t); n += 1
            txt = read_part(final); log_outbox(final, rid, "final", txt, t0); move_done(final)
            speak_part(txt); return True
        OUTBOX_SIGNAL.wait(cfg)
    log.warning("reply timeout for %s", rid)
    if not server_seen and not real_data_seen:
        SERVER["down_since"] = time.time(); CANCELLED[rid] = time.time()
        log.warning("server marked unresponsive (no outbox file for rid=%s)", rid)
        say(SERVER_DOWN_PHRASE, cfg); return False
    say("Ответ не пришёл, сэр. Попробуйте ещё раз позже.", cfg)
    return False

CACHE = os.path.join(BASE, "cache", "status.json")
def read_cache():
    try:
        with open(CACHE, encoding="utf-8-sig") as f: c = json.load(f)
        upd = datetime.datetime.fromisoformat(c["updated"])
        if upd.tzinfo is None: upd = upd.astimezone()
        age = (datetime.datetime.now().astimezone() - upd).total_seconds() / 3600
        return c.get("text", ""), age
    except Exception as e:
        log.info("no usable cache: %s", e); return None, None

# ================= aliases =================
def _norm_phrase(t):
    t = (t or "").lower().replace("ё", "е")
    return re.sub(r"[^\w\s]", " ", t).split()

def _tok_match(a, b):
    if a == b: return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b[:-1]) or b.startswith(a[:-1])): return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8

def natural_status_alias(text):
    t = " ".join(_norm_phrase(text))
    t = re.sub(r"^(ну |а )?че\b",r"\1что",t)
    # Keep mutation/instruction requests on their real route.
    if re.search(r"отмет|выполн|заверш|закро[йю]|сделан|галочк|как бы полная|как полная", t): return None
    if re.search(r"\b(добав\w*|созда\w*|удал\w*|постав\w*|отмен\w*|измени\w*|перенес\w*|напомни\w*|открой|объясни|почему|как работает)\b", t): return None
    report = bool(re.search(r"\b(статус\w*|отчет\w*|доклад\w*|сводк\w*|задач\w*)\b|что (?:там |у нас |у меня )?по делам|какие (?:у меня )?дела", t))
    if report and re.search(r"питан|калори|белк|\bед[аеуы]\b",t):
        return {"name":"food", "action":"cache_field", "field":"food"}
    if report and re.search(r"проект|депло|коммит|сайт|гитхаб",t):
        return {"name":"deploy", "action":"cache_field", "field":"deploy"}
    if report and re.search(r"задач|делам|дела\b|на сегодня|сегодняшн",t):
        return {"name":"task_status", "action":"cache_field", "field":"today"}
    if report: return {"name":"status", "action":"status"}
    if re.search(r"^(?:ну |а )?(?:что (?:там )?(?:у меня )?(?:на сегодня|по планам)|какие (?:у меня )?задачи)",t):
        return {"name":"task_status", "action":"cache_field", "field":"today"}
    return None

FILLER_TOKENS = {"сэр", "ну", "э", "эм", "а", "ага", "угу", "так"}
def filler_only(text):
    toks = _norm_phrase(text)
    if not toks: return False
    if all(t in FILLER_TOKENS for t in toks): return True
    return toks in (["да", "сэр"], ["да", "да", "сэр"], ["сэр", "да"])

def incomplete_fragment(text):
    t = " ".join(_norm_phrase(text))
    return bool(re.fullmatch(r"(?:в|на|по|с|из|о|об|для|к|у) (?:вашем|твоем|моем|этом|том|вас|меня)|(?:как|что|ну|это|там|ты|и отметил|и отметь)",t))

def match_alias(text, cfg):
    secs = SLEEP.parse(text)
    if secs: return {"name": "jarvis_sleep", "action": "jarvis_sleep", "seconds": secs}
    proactive = PROACTIVE.intent(text)
    if proactive: return proactive
    toks = _norm_phrase(text)
    if not toks: return None
    quick = QUICK.match(text,cfg)
    if quick: return quick
    # Alarm cancellation is NOT the bare stop-speech alias "отмена".
    if re.search(r"будильник", " ".join(toks)):
        return {"name":"alarm_request", "action":"webhook", "target":text}
    # A cached today snapshot cannot answer a date-specific question about another day.
    joined = " ".join(toks)
    if re.search(r"план|задач|статус|отчет|встреч|календар|питан|калори|белк",joined) and re.search(r"\b(?:завтра|послезавтра|вчера|позавчера|недел\w*|месяц\w*|январ\w*|феврал\w*|март\w*|апрел\w*|ма[йяе]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)\b",joined):
        return {"name":"dated_query", "action":"webhook", "target":text}
    natural = natural_status_alias(text)
    if natural: return natural
    fuzzy = SPEED.fuzzy_alias(text, cfg)
    if fuzzy: return fuzzy
    best, bscore = None, 0
    for al in cfg.get("aliases") or []:
        if al.get("action") == "status": continue  # handled by semantic intent above
        for ph in al.get("phrases", []):
            pt = _norm_phrase(ph)
            if not pt: continue
            if al.get("action") == "stop":
                ct = [t for t in toks if t not in ("сэр", "пожалуйста", "ну")]
                if ct != pt: continue
                score = 100 + len(pt)
                if score > bscore: best, bscore = al, score
                continue
            if al.get("action") == "smalltalk":
                ct = [t for t in toks if t not in ("сэр", "пожалуйста", "ну", "э", "эм")]
                if len(ct) != len(pt): continue
                if ct == pt: score = 100 + len(pt)
                elif all(_tok_match(a, b) or (min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75) for a, b in zip(ct, pt)): score = 20 + len(pt)
                else: continue
                if score > bscore: best, bscore = al, score
                continue
            if toks == pt: score = 100 + len(pt)
            elif len(toks) <= len(pt) + int(al.get("extra_words", 2)) and all(any(_tok_match(p, t) for t in toks) for p in pt):
                score = 10 + len(pt)
            else: continue
            if score > bscore: best, bscore = al, score
    if best: return best
    return SPEED.fuzzy_alias(text, cfg)

CACHE_HINTS = {
    "food": r"питани|ккал|килокалор|белк|съеден|калори",
    "today": r"календар|тодоист|задач|встреч|сегодня|тренировк",
    "deploy": r"проект|деплой|коммит|репозитор|гитхаб|сайт",
}

def cache_age_policy(updated, cfg, now=None):
    now = now or datetime.datetime.now().astimezone()
    dt = datetime.datetime.fromisoformat(updated)
    if dt.tzinfo is None: dt = dt.astimezone()
    local_dt = dt.astimezone(now.tzinfo)
    age = (now - dt).total_seconds() / 3600
    if age < 0 or local_dt.date() != now.date(): return "old", age
    fresh_h = float(cfg.get("cache_max_age_h", 2.5))
    stale_h = max(fresh_h, float(cfg.get("cache_stale_read_max_age_h", 3)))
    if age < fresh_h: return "fresh", age
    return ("stale" if age <= stale_h else "old"), age

def cached_status(field, cfg):
    try:
        with open(CACHE, encoding="utf-8-sig") as f: data = json.load(f)
        decision, age = cache_age_policy(data["updated"], cfg)
        body = data.get(field or "text")
        if field and not body: body = cache_field(field)[0]
        if not isinstance(body, str) or not body.strip(): return "missing", "", age
        dt = datetime.datetime.fromisoformat(data["updated"]).astimezone()
        body = re.sub(r"^(?:По данным|Данные) на[^.!?]+[.!?]\s*", "", body.strip(), flags=re.I)
        stamp = "По данным на " + JT.time_words(dt.hour, dt.minute) + ", сэр. "
        return decision, stamp + body, age
    except Exception as e:
        log.info("status snapshot unusable: %s", type(e).__name__); return "missing", "", None

def cache_stamp():
    try:
        with open(CACHE, encoding="utf-8-sig") as f: updated = json.load(f)["updated"]
        dt = datetime.datetime.fromisoformat(updated).astimezone()
        return "Данные на " + JT.time_words(dt.hour, dt.minute) + ", сэр. "
    except Exception: return ""

def cache_field(field):
    try:
        with open(CACHE, encoding="utf-8-sig") as f: c = json.load(f)
    except Exception as e:
        log.info("cache read failed: %s", e); return None, None
    v = c.get(field)
    if isinstance(v, (list, dict)): v = " ".join(str(x) for x in (v.values() if isinstance(v, dict) else v))
    if v: return str(v), "field"
    sents = re.split(r"(?<=[.!?])\s+", c.get("text", ""))
    hit = [x for x in sents[1:] if re.search(CACHE_HINTS.get(field, "$^"), x, re.I)]
    return (" ".join(hit), "derived") if hit else (None, None)

def run_alias(al, text, cfg, trig, test):
    act = al.get("action", "say"); reply = al.get("reply") or ""
    ack = lambda: say(reply or pick(cfg, "ack_command"), cfg, role="ack")
    log.info("ALIAS %s (%s) <- %r", al.get("name", "?"), act, text)
    if act == "jarvis_sleep":
        STATE["followup_eligible"] = False
        secs = int(al["seconds"])
        if test: log.info("TEST sleep %ss: no persistent change", secs)
        else: sleep_state().start(secs)
        say("Перехожу в спящий режим на " + SLEEP.label(secs) + ", сэр.", cfg)
        return
    if act == "proactive_dnd":
        if test: log.info("TEST DND=%s: no persistent change",al["enabled"])
        else: proactive_manager().set_dnd(al["enabled"])
        say(PROACTIVE.REPLIES[0 if al["enabled"] else 1],cfg)
        return
    if act == "quick2":
        keep = command_controller().execute(al,text,cfg,say,lambda value,**kw:free_phrase(value,cfg,trig,test,**kw),
                last_reply=STATE.get("last_reply", ""),last_private=STATE.get("last_reply_private",False),trigger=trig,
                confidence=STATE.get("last_input_conf",1),test=test)
        if not keep: STATE["followup_eligible"] = False
        return
    if act in ("status", "cache_field"):
        field = al.get("field") if act == "cache_field" else None
        decision, cached, age = cached_status(field, cfg)
        log.info("status cache policy=%s field=%s age_h=%s", decision, field or "all", None if age is None else round(age,3))
        if decision == "fresh":
            say_reply(cached, cfg); return
        if decision == "stale":
            spoken = cached + " Это сохранённые данные. Обновляю данные, сэр."
            # Fetch concurrently while the dated snapshot is being read.
            free_phrase(text, cfg, trig, test, ack=spoken, kind="status"); return
        free_phrase(text if field else "статус по задачам", cfg, trig, test, ack=pick(cfg, "ack_status"), kind="status")
    elif act == "time":
        now = datetime.datetime.now(); say(f"Сейчас {JT.time_words(now.hour, now.minute)}, сэр.", cfg)
    elif act == "workout":
        say(quick_facts(cfg), cfg)
    elif act == "smalltalk":
        say(smalltalk_reply(al), cfg)
    elif act == "stop":
        say(pick(cfg, "ack_stop"), cfg, role="stop_ack")
    elif act == "key":
        vk = LP.VK[al["key"]]; n = int(al.get("times", 1))
        if test: log.info("TEST: would send vk=0x%X x%d", vk, n)
        else: LP.press(vk, n)
        if not al.get("silent") and al["key"] != "mute": ack()
    elif act == "monitor_off":
        ack()
        if test: log.info("TEST: would turn monitor off")
        else: time.sleep(0.5); LP.monitor_off()
    elif act == "timer":
        secs = LP.parse_duration_s(text)
        if not secs: say("На сколько поставить таймер, сэр?", cfg); return
        LP.TIMERS.add(secs, text)
        if secs % 3600 == 0: w = f"{JT.num_ru(secs // 3600)} {JT.plural(secs // 3600, 'час', 'часа', 'часов')}"
        elif secs % 60 == 0: m = secs // 60; w = f"{JT.num_ru(m, 'f')} {JT.plural(m, 'минуту', 'минуты', 'минут')}"
        else: w = f"{JT.num_ru(secs, 'f')} {JT.plural(secs, 'секунду', 'секунды', 'секунд')}"
        say(f"Таймер на {w}, сэр.", cfg)
    elif act == "timer_cancel":
        n = LP.TIMERS.cancel(); say("Таймер отменён, сэр." if n else "Активных таймеров нет, сэр.", cfg)
    elif act == "battery":
        pct, ac = LP.battery()
        if pct is None: say("Не вижу батарею, сэр.", cfg); return
        say(f"Заряд {JT.num_ru(pct)} {JT.plural(pct, 'процент', 'процента', 'процентов')}, " + ("зарядка подключена, сэр." if ac else "работаем от батареи, сэр."), cfg)
    elif act == "temperature":
        t = LP.temperature_c()
        if t is None: say("Датчик температуры сейчас недоступен, сэр.", cfg)
        else: say(f"Температура системы {JT.num_ru(t)} {JT.plural(t, 'градус', 'градуса', 'градусов')}, сэр.", cfg)
    elif act == "open_project":
        rest = " ".join(_norm_phrase(text)); rest = re.sub(r"^.*?проект\w*\s*", "", rest)
        path, score = LP.find_project(rest, lambda w: JT._latin(re.match(r"(?s).+", w)))
        log.info("project match %r -> %s (%.2f)", rest, path, score)
        exe = LP.cursor_exe()
        if not path or score < 0.5: say("Не нашёл такой проект, сэр.", cfg); return
        if not exe: say("Не нашёл Курсор, сэр.", cfg); return
        if test: log.info("TEST: would run %s %s", exe, path)
        else: subprocess.Popen([exe, path], creationflags=0x08000000)
        ack()
    elif act == "open_github":
        url = None
        try:
            with open(CACHE, encoding="utf-8-sig") as f: pj = json.load(f).get("projects")
            for p in (pj if isinstance(pj, list) else [pj] if pj else []):
                u = p if isinstance(p, str) else (p.get("github") or p.get("url") or p.get("repo") or "")
                if u: url = u if u.startswith("http") else "https://github.com/" + u.strip("/"); break
        except Exception as e: log.info("projects field unavailable: %s", e)
        if not url:
            r = LP.recent_repo(); url = LP.remote_url(r) if r else None; log.info("recent repo %s -> %s", r, url)
        if not url: say("Не нашёл репозиторий, сэр.", cfg); return
        if test: log.info("TEST: would open %s", url)
        else: os.startfile(url)
        ack()
    elif act == "open":
        tgt = os.path.expandvars(al.get("target", ""))
        if test: log.info("TEST: would open %s (exists=%s)", tgt, os.path.exists(tgt) or tgt.startswith("http")); ack(); return
        try:
            if not re.match(r"^\w+:", tgt) or re.match(r"^[A-Za-z]:\\", tgt):
                if not os.path.exists(tgt): raise FileNotFoundError(tgt)
            os.startfile(tgt); ack()
        except Exception as e:
            log.warning("open failed %s: %s", tgt, e); say("Не нашёл приложение, сэр.", cfg)
    elif act == "lock":
        ack()
        if test: log.info("TEST: would lock"); return
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif act == "shell":
        ack()
        target = str(al.get("target", "")).strip()
        if test: log.info("TEST: would run %s", target); return
        if not target: return
        subprocess.Popen(shlex.split(target, posix=False), shell=False)
    elif act == "webhook":
        free_phrase(al.get("target") or text, cfg, trig, test, ack=reply or None)
    else:
        say(reply, cfg)

def free_phrase(text, cfg, trig, test, ack=None, listener_ack=None, kind=None, extra_payload=None):
    trace = STATE.get("trace")
    rid = trace.rid if trace is not None else str(uuid.uuid4()); res = []; STATE["rid"] = rid
    chosen_ack = ack if ack is not None else cfg.get("fast_ack", "Сейчас, сэр.")
    acknowledged = chosen_ack if listener_ack is None else listener_ack
    kind = kind or ("status" if natural_status_alias(text) else "free")
    log.info("FREE -> webhook rid=%s kind=%s listener_ack=%r: %r", rid, kind, acknowledged, text)
    th = threading.Thread(target=lambda: res.append(call_webhook(rid, text, trig, cfg, test, listener_ack=acknowledged, kind=kind, trace=trace, extra_payload=extra_payload)), daemon=True); th.start()
    perf("ack_start")
    say(chosen_ack, cfg, role="ack")
    while th.is_alive() and not interrupt.is_set(): th.join(0.1)
    if interrupt.is_set():
        CANCELLED[rid] = time.time(); log.info("webhook request abandoned rid=%s", rid); return
    if res and res[0]: wait_replies(rid, cfg, listener_ack=acknowledged, kind=kind)
    else: say("Не получилось отправить запрос, сэр.", cfg)

# ================= capture after wake =================
WAKE_TOK = re.compile(r"^(хей|эй|хэй|эх|ай|а|о|ну|слушай|джарвис\w*|жарвис\w*|джервис\w*|дарвис\w*|гарвис\w*|джарви\w*|джави\w*|харвис\w*|травис\w*|арвис\w*|рвис\w*|jarvis)$")

class Capture:
    def __init__(self, pre=None):
        self.q = queue.Queue()
        self.audio_start = time.time() - sum(len(x) for x in (pre or [])) / SR
        for x in pre or []: self.q.put(x)

def strip_wake(words):
    toks = [w for w in words]
    while toks and WAKE_TOK.match(toks[0]): toks.pop(0)
    return " ".join(toks).strip()

class AGC:
    def __init__(self, cfg):
        self.env = 0.05; self.max_g = float(cfg.get("vosk_agc_max_gain", 12)); self.tgt = float(cfg.get("vosk_agc_target_peak", 0.6))
        self.on = bool(cfg.get("vosk_agc", True)); self.gains = []
    def __call__(self, x):
        if not self.on: return x
        pk = float(np.abs(x).max()); self.env = max(pk, self.env * 0.97, 0.02)
        g = min(self.max_g, self.tgt / self.env); self.gains.append(g)
        return np.clip(x * g, -1, 1)

def grammar_phrases(cfg):
    ph = []
    for al in cfg.get("aliases") or []:
        for p in al.get("phrases", []):
            p = " ".join(_norm_phrase(p))
            if p and al.get("action") not in ("timer", "open_project"): ph.append(p)
    ph += ["расскажи статус по задачам", "что там по задачам", "что там статус по задачам", "статус моих задач", "какие у меня задачи", "что по делам", "что у меня на сегодня", "дай отчет по задачам", "статус питания", "статус по проектам"]
    ph += QUICK.PHRASES + PROACTIVE.PHRASES
    return sorted(set(ph)) + ["[unk]"]

def capture_phrase(cap, cfg, nospeech_s, skip_s=0.0, max_s=None):
    """returns (text, avg_conf, grammar_text)"""
    from vosk import KaldiRecognizer
    rec = KaldiRecognizer(STATE["model"], SR); rec.SetWords(True)
    grec = None
    if cfg.get("grammar_hint", True):
        try: grec = KaldiRecognizer(STATE["model"], SR, json.dumps(grammar_phrases(cfg), ensure_ascii=False)); grec.SetWords(True)
        except Exception as e: log.info("grammar recognizer failed: %s", e)
    agc = AGC(cfg)
    max_s = max_s or float(cfg["phrase_max_s"]); sil = float(cfg["phrase_silence_s"])
    words = []; gwords = []; t0 = time.time(); last_change = None; partial = ""; cut = True
    acoustic_last = None; noise_floor = 0.001; samples = 0
    try:
        while time.time() - t0 < max_s:
            try: x = cap.q.get(timeout=0.15)
            except queue.Empty: x = None
            if x is not None:
                samples += len(x)
                rms = float(np.sqrt(np.mean(x * x)))
                if rms > max(0.003, noise_floor * 3):
                    acoustic_last = cap.audio_start + samples / SR
                else: noise_floor = 0.98 * noise_floor + 0.02 * min(rms, 0.004)
                b = (agc(x) * 32767).astype(np.int16).tobytes()
                if grec is not None and grec.AcceptWaveform(b): gwords += json.loads(grec.Result()).get("result", [])
                if rec.AcceptWaveform(b):
                    ws = json.loads(rec.Result()).get("result", []); words += ws
                    if ws and not partial: last_change = time.time()
                    partial = ""
                else:
                    p = json.loads(rec.PartialResult()).get("partial", "")
                    if p != partial:
                        partial = p
                        if p: last_change = time.time()
                if not cap.q.empty(): continue
            has = bool(words) or bool(partial)
            if not has and time.time() - t0 > nospeech_s and (acoustic_last is None or time.time() - acoustic_last > 0.5): cut = False; break
            if has and last_change and time.time() - last_change > sil and (acoustic_last is None or time.time() - acoustic_last > sil): cut = False; break
        words += json.loads(rec.FinalResult()).get("result", [])
        if grec is not None: gwords += json.loads(grec.FinalResult()).get("result", [])
    finally:
        if STATE["capture"] is cap: STATE["capture"] = None
    kept = [w for w in words if w.get("end", 99) > skip_s]
    # Strip the recognized wake name, not a fixed 1.35 s of possible command audio.
    wake_indices = [i for i,w in enumerate(kept[:8]) if re.fullmatch(r"(?:джарвис|жарвис|джервис|дарвис|гарвис|джарви|джави|харвис|арвис|jarvis)\w*", w["word"])]
    if wake_indices: kept = kept[wake_indices[-1]+1:]
    toks = [w["word"] for w in kept]
    while toks and WAKE_TOK.match(toks[0]): toks.pop(0); kept.pop(0)
    text = " ".join(toks).strip()
    conf = sum(w.get("conf", 1) for w in kept) / len(kept) if kept else 0.0
    gk = [w for w in gwords if w.get("end", 99) > skip_s and w["word"] != "[unk]"]
    gtext = " ".join(w["word"] for w in gk); gconf = sum(w.get("conf", 1) for w in gk) / len(gk) if gk else 0.0
    gmin = min(agc.gains) if agc.gains else 1
    log.info("capture: raw=%r -> %r conf=%.2f | grammar=%r conf=%.2f | agc gain min=%.1f (%.1fs)",
             " ".join(w["word"] for w in words), text, conf, gtext, gconf, gmin, time.time() - t0)
    if kept:
        endpoint_lag = max(0.0, time.time() - (cap.audio_start + kept[-1].get("end", 0)))
        log.info("capture endpoint lag_s=%.3f silence_s=%.2f (audio timestamp estimate)", endpoint_lag, sil)
    tr = STATE.get("trace")
    if tr is not None and kept:
        tr.mark("speech_end", at=time.perf_counter() - endpoint_lag, estimated=True)
    STATE["last_input_conf"] = conf
    STATE["last_capture"] = {"words": kept, "hit_max": cut and bool(kept)}
    STATE["last_input_end"] = time.monotonic() - endpoint_lag if kept else None
    perf("recognized", confidence=round(conf,3))
    return text, conf, (gtext if gconf >= 0.75 else "")

def drop(reason, text):
    """Garbled / background speech: log it and stay silent."""
    STATE["dropped"] = True
    log.info("dropped silently (%s): %r", reason, text)
    return "", False

def choose(text, conf, gtext, cfg, followup=False):
    """pick final phrase + whether it is understood"""
    STATE["dropped"] = False
    if text and filler_only(text) and not (CMDS is not None and getattr(CMDS, "pending_shutdown", None)):
        log.info("filler-only/echo transcript ignored: %r", text); return "", False
    al = match_alias(text, cfg) if text else None
    ga = match_alias(gtext, cfg) if gtext else None
    if al:
        if al.get("action") in ("status","cache_field","time","workout") and conf<float(cfg.get("min_conf",0.55)) and not (gtext and ga):
            log.info("local intent rejected: low ASR confidence %.2f",conf); return text,False
        if al.get("action") in ("quick2","proactive_dnd","jarvis_sleep") and conf<float(cfg.get("min_conf",0.55)):
            log.info("quick command rejected: low ASR confidence %.2f",conf); return text, False
        if al.get("_fuzzy") and conf < float(cfg.get("min_conf",0.55)):
            log.info("fuzzy intent rejected: low ASR confidence %.2f",conf); return text, False
        exact = any(_norm_phrase(text) == _norm_phrase(p) for p in al.get("phrases", []))
        if al.get("action") == "smalltalk" and not exact and conf < 0.8 and ga and ga.get("action") == "smalltalk":
            log.info("grammar smalltalk wins over fuzzy guess: %r (free %r conf %.2f)", gtext, text, conf); return gtext, True
        return text, True
    if incomplete_fragment(text):
        return drop("fragment", text)
    safe_grammar = ga and ga.get("action") in ("smalltalk", "status", "cache_field", "time", "workout", "stop")
    if gtext and safe_grammar and not followup and (not text or conf < 0.8):
        log.info("grammar hint wins: %r (free %r conf %.2f)", gtext, text, conf); return gtext, True
    if not text: return "", False
    meta = STATE.get("last_capture") or {}
    words = meta.get("words") or [{"word": w, "conf": conf} for w in _norm_phrase(text)]
    reason = GATE.reject_reason(words, cfg, followup=followup, hit_max=bool(meta.get("hit_max")))
    if reason: return drop(reason, text)
    return text, True

def _handle_turn(trig, cap, text, test, skip_s):
    cfg = load_cfg()
    try:
        log.info("TRIGGER %s%s", trig, " (test)" if test else "")
        if trig == "stop_ack":
            perf("route", route="stop_ack")
            STATE["stop_ack_active"] = True
            ack = pick(cfg, "ack_stop"); log.info("stop ack begin: %s interrupt=%s", ack, interrupt.is_set())
            result = say(ack, cfg, role="stop_ack")
            log.info("stop ack complete: played=%s", result); return
        if trig == "proactive":
            item=text if isinstance(text,dict) else {}
            perf("route",route="proactive_"+str(item.get("kind","file")))
            try:
                if item.get("expires") is None or time.time()<item["expires"]:
                    STATE["followup_eligible"]=True
                    say(item.get("text",""),cfg)
            finally:
                if not test: proactive_manager().complete(item,interrupt.is_set())
            return
        if trig == "sleep_end":
            perf("route", route="sleep_end"); say(SLEEP_END_PHRASE, cfg); return
        if trig == "timer_fire":
            perf("route", route="timer_fire")
            notice = text if isinstance(text,dict) else {}
            try:
                beep()
                if notice.get("kind") != "reminder": beep()
            except Exception: pass
            say(notice.get("label") or "Сэр, время вышло.", cfg); return
        ok = True
        if text is None:
            text, conf, g = ("", 0, "") if cap is None else capture_phrase(cap, cfg, float(cfg["phrase_wait_s"]), skip_s)
            text, ok = choose(text, conf, g, cfg)
            if STATE["dropped"]: return
        else:
            text = " ".join(t for t in _norm_phrase(text)); toks = text.split()
            while toks and WAKE_TOK.match(toks[0]): toks.pop(0)
            text = " ".join(toks)
            if trig != "followup":
                STATE["last_input_conf"] = 1.0
                STATE["last_input_end"] = None
        if not text:
            say(pick(cfg, "ack_wake"), cfg, role="wake")
            if interrupt.is_set(): return
            cap2 = Capture(); STATE["capture"] = cap2
            text, conf, g = capture_phrase(cap2, cfg, float(cfg["followup_listen_s"]))
            raw2 = text
            text, ok = choose(text, conf, g, cfg)
            if not text and (not g or filler_only(raw2)):
                log.info("no follow-up phrase"); return
        if interrupt.is_set(): return
        if not ok or not text:
            # Never "sorry, I did not catch that": unclear input is dropped silently.
            log.info("not understood -> silent: %r", text); return
        perf("recognized")
        confirmation = command_controller().confirmation(text,trig,STATE.get("last_input_conf",0),heard_at=STATE.get("last_input_end"))
        al = ({"name":"shutdown_confirmation", "action":"quick2", "cmd":"shutdown_confirm", **confirmation} if confirmation is not None else match_alias(text,cfg))
        perf("route", route=(al.get("name", "local") if al else "webhook"))
        STATE["followup_eligible"] = not (al and al.get("action") == "stop")
        if al: run_alias(al, text, cfg, trig, test)
        else: free_phrase(text, cfg, trig, test)
    except Exception as e:
        log.exception("handle error: %s", e)
    finally:
        STATE["capture"] = None; STATE["stop_ack_active"] = False

def followup_echo(text, spoken):
    tt = _norm_phrase(text)
    if len(tt) < 2: return False
    sentences = re.split(r"[.!?…]+", spoken or "")
    return any(tt == _norm_phrase(sent) for sent in sentences) or tt == _norm_phrase(spoken)

def followup_seconds(cfg, spoken):
    key = "followup_question_window_s" if (spoken or "").rstrip().endswith("?") else "followup_window_s"
    cap_s = float(GATE.setting(cfg, "followup_window_cap_s"))
    return max(0.0, min(30.0, cap_s, float(cfg.get(key, 10 if key == "followup_question_window_s" else 7))))

def handle(trig, cap, text, test, skip_s, trace=None):
    """Own the entire short conversation; only silence/stop/limit returns to wake mode."""
    try:
        turns = 0
        STATE["trace"] = trace or SPEED.Trace(trig)
        STATE["trace"].meta["test"] = bool(test)
        while True:
            STATE["reply_parts"] = []
            STATE["followup_eligible"] = False
            serial = STATE["speech_serial"]
            _handle_turn(trig, cap, text, test, skip_s)
            STATE["trace"].finish("interrupted" if interrupt.is_set() else "done")
            cfg = load_cfg()
            if interrupt.is_set() or not cfg.get("followup_enabled", True): break
            if not STATE["followup_eligible"] or STATE["speech_serial"] == serial: break
            if turns >= max(0, int(cfg.get("followup_max_turns", 8))):
                log.info("follow-up turn limit -> wake mode"); break
            spoken = STATE["last_spoken"]
            window = followup_seconds(cfg, spoken)
            if CMDS is not None and CMDS.pending_shutdown:
                window = max(0.0,CMDS.pending_shutdown["expires"]-CMDS.clock())
            if window <= 0: break
            guard = max(0.0, min(2.0, float(cfg.get("followup_echo_guard_s", 0.3))))
            STATE["followup_guard"] = True
            # Based on actual playback end, not synthesis start or webhook acknowledgement.
            delay = max(0.0, STATE["last_spoken_end"] + guard - time.monotonic())
            if interrupt.wait(delay): break
            log.info("follow-up open window_s=%.1f guard_s=%.2f question=%s turn=%d", window, guard, spoken.rstrip().endswith("?"), turns+1)
            STATE["trace"] = SPEED.Trace("followup")
            STATE["trace"].meta["test"] = bool(test)
            cap = Capture(); STATE["capture"] = cap; STATE["followup_guard"] = False
            text, conf, grammar = capture_phrase(cap, cfg, window, max_s=window + float(cfg["phrase_max_s"]))
            if interrupt.is_set(): break
            if not text or conf < float(cfg.get("followup_min_conf", 0.65)):
                STATE["trace"].finish("silence")
                log.info("follow-up close: silence/low confidence text=%r conf=%.2f", text, conf); break
            if followup_echo(text, spoken):
                STATE["trace"].finish("echo")
                log.info("follow-up close: likely speaker echo %r", text); break
            chosen, ok = choose(text, conf, grammar, cfg, followup=True)
            if not ok or not chosen:
                STATE["trace"].finish("fragment")
                log.info("follow-up close: fragment/garbage %r", text); break
            text = chosen; cap = None; skip_s = 0.0; trig = "followup"; turns += 1
            log.info("follow-up accepted conf=%.2f text=%r", conf, text)
    except Exception:
        log.exception("conversation handler error")
    finally:
        if STATE.get("trace") is not None: STATE["trace"].finish("interrupted" if interrupt.is_set() else "done")
        STATE["trace"] = None
        if CMDS is not None: CMDS.clear_pending()
        STATE["capture"] = None; STATE["followup_guard"] = False
        STATE["stop_ack_active"] = False; busy.clear()

# ================= clap detector =================
class ClapDetector:
    """Clap = sharp onset (attack) + loud vs background + fast decay. Two claps, isolated, 0.12-0.9 s apart.
    Reverb tails / bounces right after a clap are ignored (clap_tail_s); weak noise (< clap_noise_rel * clap peak) is ignored."""
    def __init__(self):
        self.bg = 0.002; self.prev_r = 0.0; self.cur = None; self.events = []; self.last_log = 0; self.last_clap_t = -9; self.last_noise_t = -9
    def feed(self, x, pos, c):
        fl = 160
        for i in range(0, len(x) - fl + 1, fl):
            f = x[i:i + fl]; r = float(np.sqrt(np.mean(f * f))); pk = float(np.abs(f).max()); t = (pos + i) / SR
            if self.cur is None:
                att = r / max(self.prev_r, 1e-5)
                in_tail = t - self.last_clap_t < c["clap_tail_s"]
                if pk >= c["clap_min_peak"] and r >= c["clap_ratio"] * self.bg and att >= c["clap_attack"]:
                    self.cur = {"t": t, "pk": pk, "r": r, "bg": self.bg, "att": att}
                elif (not in_tail and pk >= c["clap_log_min_peak"] and r >= 4 * self.bg and att >= c["clap_noise_attack"]
                      and t - self.last_noise_t > 0.1):
                    self.events.append({"t": t, "ok": False, "pk": pk, "att": att}); self.last_noise_t = t
                    if t - self.last_log > 0.3:
                        log.info("clap near-miss: peak=%.3f rms=%.4f bg=%.4f attack=%.1f", pk, r, self.bg, att); self.last_log = t
                if r < self.bg: self.bg = 0.9 * self.bg + 0.1 * r
                elif not in_tail: self.bg = 0.998 * self.bg + 0.002 * min(r, 20 * self.bg)
                self.bg = max(self.bg, 1e-4)
            else:
                cu = self.cur; cu["pk"] = max(cu["pk"], pk); cu["r"] = max(cu["r"], r); dur = t - cu["t"]
                if r < cu["r"] * c["clap_decay"] or dur > c["clap_max_len_s"]:
                    ok = dur <= c["clap_max_len_s"]
                    log.info("clap candidate: peak=%.3f rms=%.4f bg=%.4f attack=%.1f dur=%.3f -> %s", cu["pk"], cu["r"], cu["bg"], cu["att"], dur, "ok" if ok else "too long")
                    self.events.append({"t": cu["t"], "ok": ok, "pk": cu["pk"], "att": cu["att"]}); self.cur = None
                    self.last_clap_t = t
            self.prev_r = r
        now_t = (pos + len(x)) / SR
        if self.cur is None and self.events and now_t - self.events[-1]["t"] >= c["clap_quiet_s"]:
            cl = [self.events[-1]]
            for e in reversed(self.events[:-1]):
                if cl[0]["t"] - e["t"] < max(c["clap_quiet_s"], c["clap_gap_max_s"]): cl.insert(0, e)
                else: break
            self.events = []
            oks = [e for e in cl if e["ok"]]
            if not oks: return False
            ref = max(e["pk"] for e in oks)
            sig = [e for e in cl if e["ok"] or e["pk"] >= c["clap_noise_rel"] * ref]
            desc = ", ".join(f"{e['t'] - cl[0]['t']:+.2f}s pk={e['pk']:.2f} att={e['att']:.0f}{'*' if e['ok'] else ''}" for e in cl)
            if len(sig) == 2 and all(e["ok"] for e in sig):
                g = sig[1]["t"] - sig[0]["t"]; sim = max(sig[0]["pk"], sig[1]["pk"]) / max(min(sig[0]["pk"], sig[1]["pk"]), 1e-4)
                if c["clap_gap_min_s"] <= g <= c["clap_gap_max_s"] and sim <= c["clap_peak_similarity"]:
                    log.info("DOUBLE CLAP gap=%.2f sim=%.1f [%s]", g, sim, desc); return True
                log.info("clap pair rejected: gap=%.2f sim=%.1f [%s]", g, sim, desc)
            else:
                log.info("clap cluster rejected: %d significant (%d clap-like) [%s]", len(sig), len(oks), desc)
        return False

def pick_device(cfg):
    keys = [k.lower() for k in cfg.get("mic_name_contains", ["Intel", "Smart Sound", "массив", "Microphone Array"])]
    devs = sd.query_devices(); apis = sd.query_hostapis(); cands = []
    for i, d in enumerate(devs):
        if d["max_input_channels"] < 1: continue
        n = d["name"].lower()
        if any(k in n for k in keys):
            api = apis[d["hostapi"]]["name"]
            cands.append(({"Windows WASAPI": 0, "MME": 1, "Windows DirectSound": 2}.get(api, 3), i, d["name"], api))
    for pr, i, name, api in sorted(cands):
        try:
            sd.check_input_settings(device=i, samplerate=SR, channels=1, dtype="float32")
            log.info("mic selected: [%d] %s (%s)", i, name, api); return i
        except Exception as e:
            log.info("mic %d %s (%s) rejected: %s", i, name, api, e)
    log.warning("no matching mic, using default"); return None

def corroborated_stop(ph, free_text):
    pt = _norm_phrase(ph); ft = _norm_phrase(free_text)
    if not pt or "[unk]" in free_text or re.search(r"\b(?:не|нет)\b", free_text): return False
    return any(ft[i:i+len(pt)] == pt for i in range(len(ft)-len(pt)+1))

def stop_candidate(ph, conf, echo, cfg):
    normalized = " ".join(_norm_phrase(ph))
    allowed = {" ".join(_norm_phrase(p)) for p in cfg.get("stop_phrases", [])}
    return normalized in allowed and conf >= float(cfg.get("bargein_min_conf", 0.60)) and not echo

PRO_MANAGER = None
def proactive_manager():
    global PRO_MANAGER
    if PRO_MANAGER is None: PRO_MANAGER = PROACTIVE.Manager(BASE)
    return PRO_MANAGER

def request_morning(job,cfg,test=False):
    extra={k:v for k,v in job.items() if k not in ("request_id","kind","date","attempts","retry_at")}
    text="Составь короткий утренний брифинг по моим свежим данным. Ответ только в указанном proactive outbox, без вводного подтверждения."
    result=False
    try: result=call_webhook(job["request_id"],text,"presence",cfg,test,listener_ack="",kind="morning_briefing",extra_payload=extra)
    finally:
        if not test: proactive_manager().morning_result(job,result,cfg)
    log.info("morning briefing POST date=%s ok=%s",job.get("local_date"),bool(result))

def ring_audio(ring, a, b):
    """Samples [a, b) from the ring buffer of (start_pos, chunk)."""
    parts = []
    for p, c in ring:
        lo, hi = max(a, p), min(b, p + len(c))
        if hi > lo: parts.append(c[lo - p:hi - p])
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

def free_words(model, audio, cfg):
    """Free-vocabulary transcript of a short clip (grammar recognizers force every sound into the wake word)."""
    from vosk import KaldiRecognizer
    r = KaldiRecognizer(model, SR); r.SetWords(True); agc = AGC(cfg)
    for i in range(0, len(audio), CHUNK):
        r.AcceptWaveform((agc(audio[i:i + CHUNK]) * 32767).astype(np.int16).tobytes())
    return json.loads(r.FinalResult()).get("result", [])

def verify_wake(model, ring, a, b, cfg, need=(), min_conf=None):
    """True when a free transcript of [a, b) contains the wake name (and every word in ``need``) confidently."""
    if not GATE.setting(cfg, "wake_verify_enabled"): return True
    t0 = time.monotonic(); ws = free_words(model, ring_audio(ring, a, b), cfg)
    mc = float(min_conf if min_conf is not None else GATE.setting(cfg, "wake_verify_min_conf"))
    ok = GATE.wake_word_confirmed(ws, mc) and all(any(w.get("word") == n and w.get("conf", 0) >= mc for w in ws) for n in need)
    log.info("wake verify %s: free=%r (%.2fs)", "OK" if ok else "REJECTED",
             " ".join("%s:%.2f" % (w.get("word"), w.get("conf", 0)) for w in ws), time.monotonic() - t0)
    return ok

def main():
    cfg = load_cfg()
    LP.TIMERS = command_controller().timers
    pm=proactive_manager(); next_proactive=0.0
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    mdir = [d for d in os.listdir(os.path.join(BASE, "models")) if d.startswith("vosk-model")]
    ready = threading.Event(); model_error = []; model_box = []
    def warm_vosk():
        t0 = time.monotonic()
        try: model_box.append(Model(os.path.join(BASE, "models", mdir[0])))
        except Exception as e: model_error.append(e)
        finally:
            ready.set(); log.info("vosk background warmup %.3fs", time.monotonic()-t0)
    threading.Thread(target=warm_vosk, name="vosk-warmup", daemon=True).start()
    threading.Thread(target=precache, args=(cfg,), name="tts-warmup", daemon=True).start()
    OUTBOX_SIGNAL.start(cfg.get("outbox_watch_enabled", True),cfg.get("outbox_event_batch_s",0.02))
    while not ready.wait(0.1):
        if os.path.exists(STOP_FILE):
            RUNTIME.mark_stop(BASE); os.remove(STOP_FILE); OUTBOX_SIGNAL.stop(); return
    if model_error: raise model_error[0]
    model = model_box[0]; STATE["model"] = model
    def wake_rec():
        r = KaldiRecognizer(model, SR, json.dumps(["джарвис", "хей джарвис", "эй джарвис", "[unk]"], ensure_ascii=False))
        r.SetWords(True); return r
    def sleep_rec():
        r = KaldiRecognizer(model, SR, json.dumps(list(SLEEP.WAKE_PHRASES) + ["[unk]"], ensure_ascii=False))
        r.SetWords(True); return r
    srec = None; sbase = 0; wake_check = None
    if sleep_state().active(): log.info("sleep mode active for %.0fs more", sleep_state().remaining())
    oww = None
    if cfg["oww_enabled"]:
        try:
            from openwakeword.model import Model as OWW
            oww = OWW(wakeword_models=[os.path.join(BASE, "models", "hey_jarvis_v0.1.onnx")], inference_framework="onnx")
            log.info("openWakeWord loaded")
        except Exception as e:
            log.warning("openWakeWord unavailable: %s", e)
    clap = ClapDetector()

    def start(trig, pre=None, text=None, test=False, skip_s=0.0):
        interrupt.clear(); busy.set()
        cap = Capture(pre) if (text is None and pre is not None) else None
        STATE["capture"] = cap
        threading.Thread(target=handle, args=(trig, cap, text, test, skip_s, SPEED.Trace(trig)), daemon=True).start()

    dev = pick_device(cfg)
    stream = sd.InputStream(device=dev, samplerate=SR, channels=1, dtype="float32", blocksize=CHUNK, callback=cb)
    stream.start()
    log.info("listening (v3.14.0) on device %s: %s", dev, sd.query_devices(dev)["name"] if dev is not None else sd.query_devices(kind="input")["name"])
    pos = 0; ring = collections.deque(maxlen=int(8 * SR / CHUNK)); wrec = wake_rec(); wbase = 0
    last_end = 0.0; lastlvl = time.time(); was_busy = False; barge_armed = False; pending = None
    TEST_BARGE = os.path.join(BASE, "test_bargein"); brec = None; brfree = None; free_last = (0, ""); bagc = None; last_clean = 0; bframes = 0
    def stop_rec(c):
        ph = sorted(set(" ".join(_norm_phrase(p)) for p in c.get("stop_phrases", [])) - {""})
        r = KaldiRecognizer(model, SR, json.dumps(ph + ["[unk]"], ensure_ascii=False)); r.SetWords(True); return r
    def do_stop(reason):
        log.info("STOP barge-in (%s): speech stopped", reason)
        interrupt.set(); sd.stop()
        if STATE.get("rid"): CANCELLED[STATE["rid"]] = time.time()
        STATE["stop_pending"] = True
    while True:
        try:
            if os.path.exists(STOP_FILE):
                RUNTIME.mark_stop(BASE); os.remove(STOP_FILE); log.info("stop file -> intentional exit"); interrupt.set(); sd.stop(); break
            if not busy.is_set() and os.path.exists(TEST_TRIGGER):
                tt = read_part(TEST_TRIGGER).strip(); os.remove(TEST_TRIGGER); cfg = load_cfg()
                log.info("test_trigger %r", tt)
                if tt.lower() in ("clap",): start("clap", text="", test=True)
                elif tt.lower() in ("", "wake", "джарвис", "хей джарвис"): start("wake_word", text="", test=True)
                else: start("wake_word", text=tt, test=True)
            sleeping = sleep_state().active()
            if not busy.is_set() and not was_busy and sleep_state().poll(WAKE_FILE):
                srec = None; start("sleep_end", text=""); continue
            if time.monotonic()>=next_proactive:
                next_proactive=time.monotonic()+max(1,float(cfg.get("proactive_tick_s",5)))
                job=pm.tick(cfg)
                if job: threading.Thread(target=request_morning,args=(job,dict(cfg)),name="morning-post",daemon=True).start()
                if not sleeping and not busy.is_set() and not was_busy and pending is None and not STATE["stop_pending"]:
                    item=pm.take(cfg)
                    if item: start("proactive",text=item)
            if not sleeping and not busy.is_set() and not was_busy and pending is None and not STATE["stop_pending"] and pm.can_speak(cfg):
                for notice in LP.TIMERS.pop_fired(limit=1): start("timer_fire", text=notice, test=False); break
            if time.time() - lastlvl > cfg["level_log_interval_s"]:
                n = max(levels["n"], 1)
                log.info("mic level: peak=%.3f avg_rms=%.4f chunks=%d", levels["max"], levels["sum"] / n, levels["n"])
                levels.update(max=0.0, sum=0.0, n=0); lastlvl = time.time()
            try: x = audio_q.get(timeout=0.3)
            except queue.Empty: continue
            st = pos; pos += len(x); ring.append((st, x))
            levels["max"] = max(levels["max"], float(np.abs(x).max())); levels["sum"] += float(np.sqrt(np.mean(x * x))); levels["n"] += 1
            i16 = (np.clip(x, -1, 1) * 32767).astype(np.int16)
            cap = STATE["capture"]
            if cap is not None: cap.q.put(x)
            sc = max(oww.predict(i16).values()) if oww is not None else 0.0
            if time.time() - last_clean > 2:
                last_clean = time.time()
                for rid_c, tc in list(CANCELLED.items()):
                    if time.time() - tc > 900: CANCELLED.pop(rid_c, None); continue
                    for fn in os.listdir(OUTBOX):
                        if fn.startswith(rid_c):
                            try: os.remove(os.path.join(OUTBOX, fn)); log.info("dropped cancelled outbox part %s", fn)
                            except Exception as e: log.info("drop failed %s: %s", fn, e)
            if busy.is_set():
                if not was_busy:
                    brec = stop_rec(cfg); bagc = AGC(cfg)
                    brfree = KaldiRecognizer(model, SR); brfree.SetWords(True); free_last = (0, ""); bframes=0
                was_busy = True
                if cap is None and not interrupt.is_set() and not STATE["stop_ack_active"] and not STATE["followup_guard"]:
                    if os.path.exists(TEST_BARGE):
                        tb = read_part(TEST_BARGE).strip(); os.remove(TEST_BARGE); log.info("test_bargein %r (speaking=%s)", tb, speaking.is_set())
                        do_stop("test: " + tb); continue
                    try:
                        bb = (bagc(x) * 32767).astype(np.int16).tobytes()
                        borigin=st-bframes; bframes+=len(x)
                        if brfree.AcceptWaveform(bb):
                            fr = json.loads(brfree.Result())
                            fw = fr.get("result", [])
                            fc = sum(w.get("conf",0) for w in fw) / max(1,len(fw))
                            free_last = (time.monotonic(), fr.get("text", "") if fc >= 0.5 else "")
                            if PROACTIVE.priority_candidate(fr.get("text",""),fc,STATE["speaking_text"],cfg) and any(w.get("word") in ("джарвис","жарвис","джервис","дарвис","гарвис","джарви","джави","jarvis") and w.get("conf",0)>=float(cfg.get("priority_wake_min_conf",.85)) for w in fw[:3]):
                                log.info("PRIORITY vosk wake conf=%.2f -> interrupt and capture",fc)
                                interrupt.set(); sd.stop()
                                if STATE.get("rid"): CANCELLED[STATE["rid"]]=time.time()
                                wake=next((w for w in fw[:3] if w.get("word") in ("джарвис","жарвис","джервис","дарвис","гарвис","джарви","джави","jarvis")),None)
                                pending=borigin+int((wake.get("start",0) if wake else 0)*SR)-int(.25*SR)
                                continue
                        if brec.AcceptWaveform(bb):
                            ws = json.loads(brec.Result()).get("result", [])
                            if ws:
                                conf = sum(w.get("conf", 0) for w in ws) / len(ws); ph = " ".join(w["word"] for w in ws)
                                echo = any(w["word"].replace("ё", "е") in STATE["speaking_text"] for w in ws)
                                partial_free = json.loads(brfree.PartialResult()).get("partial", "")
                                recent_free = free_last[1] if time.monotonic() - free_last[0] < 1.2 else ""
                                corroborated = corroborated_stop(ph, partial_free) or corroborated_stop(ph, recent_free)
                                ok = stop_candidate(ph, conf, echo, cfg) and corroborated
                                log.info("barge-in candidate %r conf=%.2f echo=%s speaking=%s free=%r corroborated=%s -> %s", ph, conf, echo, speaking.is_set(), partial_free or recent_free, corroborated, "STOP" if ok else "ignored")
                                if ok: do_stop(ph); continue
                    except Exception as e: log.info("barge recognizer error: %s", e)
                if cap is None and oww is not None and not STATE["stop_ack_active"] and not STATE["followup_guard"]:
                    if sc < 0.2: barge_armed = True
                    elif barge_armed and sc >= cfg["barge_in_threshold"] and not interrupt.is_set():
                        log.info("BARGE-IN oww %.2f -> interrupt", sc); interrupt.set(); sd.stop()
                        if STATE.get("rid"): CANCELLED[STATE["rid"]] = time.time()
                        pending = st + len(x) - int(cfg["wake_prebuffer_s"] * SR)
                continue
            if was_busy:
                was_busy = False; last_end = time.time(); wrec = wake_rec(); wbase = pos; wake_check = None; clap.events = []; clap.cur = None
                if oww is not None: oww.reset()
                cfg = load_cfg(); STATE["rid"] = None
                if STATE["stop_pending"]:
                    STATE["stop_pending"] = False; pending = None; start("stop_ack", text=""); continue
                if pending is not None:
                    pre = [c for (p, c) in ring if p + len(c) > pending]; pending = None; barge_armed = False
                    start("wake_word", pre=pre, skip_s=0.0); continue
            if sleeping:
                # Sleep: no clap, no wake word, no follow-ups. Only a strict «Джарвис, проснись».
                wake_check = None
                if srec is None: srec = sleep_rec(); sbase = st
                if srec.AcceptWaveform(i16.tobytes()):
                    ws = json.loads(srec.Result()).get("result", [])
                    said = " ".join(w.get("word", "") for w in ws)
                    if SLEEP.is_wake_phrase(said) and min(w.get("conf", 0) for w in ws) >= 0.9:
                        a = sbase + int((ws[0]["start"] - 0.45) * SR); b = sbase + int((ws[-1]["end"] + 0.3) * SR)
                        if verify_wake(model, ring, a, b, cfg, need=("проснись",), min_conf=GATE.setting(cfg, "sleep_wake_min_conf")):
                            sleep_state().stop("phrase"); srec = None
                            start("sleep_end", text=""); continue
                continue
            srec = None
            trig = None; frm = None; skip = 0.0
            if cfg["clap_enabled"] and clap.feed(x, st, cfg): trig = "clap"
            if cfg["wake_word_enabled"] and not trig:
                if sc >= cfg["oww_threshold"] and wake_check is None:
                    log.info("oww score %.2f", sc)
                    frm = st + len(x) - int(cfg["wake_prebuffer_s"] * SR)
                    if sc >= float(GATE.setting(cfg, "oww_strong_threshold")): trig = "wake_word"
                    else: wake_check = {"a": frm, "b": pos + int(0.3 * SR), "frm": frm, "src": "oww"}
                if wrec.AcceptWaveform(i16.tobytes()):
                    res = json.loads(wrec.Result())
                    ws = [w for w in res.get("result", []) if w.get("word") == "джарвис"]
                    if ws and ws[0].get("conf", 0) >= cfg["vosk_wake_min_conf"]:
                        if not trig and (wake_check is None or wake_check["src"] == "oww"):
                            log.info("vosk wake candidate conf %.2f", ws[0]["conf"])
                            wake_check = {"a": wbase + int((ws[0]["start"] - float(GATE.setting(cfg, "wake_verify_pre_s"))) * SR),
                                          "b": wbase + int((ws[-1]["end"] + float(GATE.setting(cfg, "wake_verify_post_s"))) * SR),
                                          "frm": wbase + int(ws[-1]["end"] * SR) - int(0.3 * SR), "src": "vosk"}
                    elif ws: log.info("vosk wake rejected conf %.2f", ws[0].get("conf", 0))
                if not trig and wake_check is not None and pos >= wake_check["b"]:
                    wc, wake_check = wake_check, None
                    if verify_wake(model, ring, wc["a"], wc["b"], cfg):
                        trig = "wake_word"; frm = wc["frm"]; skip = 0.0
            if trig and time.time() - last_end > cfg["cooldown_s"]:
                barge_armed = False
                if trig == "clap": start("clap", text="")
                else:
                    pre = [c for (p, c) in ring if p + len(c) > frm]
                    start("wake_word", pre=pre, skip_s=skip)
        except Exception as e:
            log.exception("main loop error: %s", e); time.sleep(0.5)
    OUTBOX_SIGNAL.stop()

if __name__ == "__main__":
    guard=RUNTIME.Singleton(BASE,"listener")
    if not guard.acquire():
        log.info("listener already running; duplicate start ignored"); raise SystemExit(0)
    try: main()
    except Exception as e:
        log.exception("fatal: %s", e); raise
    finally: guard.close()
