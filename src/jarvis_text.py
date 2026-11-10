# Text normalisation + stress for Jarvis TTS (Silero: '+' before stressed vowel)
import re, time, logging, os, threading
log = logging.getLogger("jarvis")

# ---------------- numbers ----------------
def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11: return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14: return few
    return many

_U = {"m": ["ноль","один","два","три","четыре","пять","шесть","семь","восемь","девять"],
      "f": ["ноль","одна","две","три","четыре","пять","шесть","семь","восемь","девять"]}
_TEEN = ["десять","одиннадцать","двенадцать","тринадцать","четырнадцать","пятнадцать","шестнадцать","семнадцать","восемнадцать","девятнадцать"]
_TENS = ["","","двадцать","тридцать","сорок","пятьдесят","шестьдесят","семьдесят","восемьдесят","девяносто"]
_HUND = ["","сто","двести","триста","четыреста","пятьсот","шестьсот","семьсот","восемьсот","девятьсот"]

def num_ru(n, g="m"):
    n = int(n)
    if n < 0: return "минус " + num_ru(-n, g)
    if n == 0: return "ноль"
    w = []
    if n >= 1_000_000:
        t = n // 1_000_000; n %= 1_000_000
        w.append(num_ru(t) + " " + plural(t, "миллион", "миллиона", "миллионов"))
    if n >= 1000:
        t = n // 1000; n %= 1000
        w.append(num_ru(t, "f") + " " + plural(t, "тысяча", "тысячи", "тысяч"))
    if n >= 100: w.append(_HUND[n // 100]); n %= 100
    if 10 <= n < 20: w.append(_TEEN[n - 10]); n = 0
    if n >= 20: w.append(_TENS[n // 10]); n %= 10
    if n: w.append(_U[g][n])
    return " ".join(x for x in w if x)

def time_words(h, m):
    h, m = int(h), int(m)
    hours = f"{num_ru(h)} {plural(h, 'час', 'часа', 'часов')}"
    if m == 0: return hours + " ровно"
    return hours + f" {num_ru(m, 'f')} {plural(m, 'минута', 'минуты', 'минут')}"

UNITS = {  # unit regex -> (gender, one, few, many)
    "ккал": ("f", "килокалория", "килокалории", "килокалорий"),
    "кг": ("m", "килограмм", "килограмма", "килограммов"),
    "гр": ("m", "грамм", "грамма", "граммов"),
    "г": ("m", "грамм", "грамма", "граммов"),
    "мин": ("f", "минута", "минуты", "минут"),
    "ч": ("m", "час", "часа", "часов"),
    "км": ("m", "километр", "километра", "километров"),
    "%": ("m", "процент", "процента", "процентов"),
}

def _num_tok(s):
    s = s.replace(",", ".")
    if "." in s:
        a, b = s.split(".", 1)
        if b.strip("0") == "": return int(a), num_ru(int(a))
        return None, fraction_words(s)
    return int(s), num_ru(int(s))

def _units(m):
    n, w = _num_tok(m.group(1))
    g, one, few, many = UNITS[m.group(2).lower()]
    if n is None: return f"{w} {few}"
    w = num_ru(n, g)
    return f"{w} {plural(n, one, few, many)}"

# v3.8: nominative and genitive numbers in full status units.
_GU = ["нуля", "одного", "двух", "трёх", "четырёх", "пяти", "шести", "семи", "восьми", "девяти"]
_GT = ["десяти", "одиннадцати", "двенадцати", "тринадцати", "четырнадцати", "пятнадцати", "шестнадцати", "семнадцати", "восемнадцати", "девятнадцати"]
_GD = ["", "", "двадцати", "тридцати", "сорока", "пятидесяти", "шестидесяти", "семидесяти", "восьмидесяти", "девяноста"]
_GH = ["", "ста", "двухсот", "трёхсот", "четырёхсот", "пятисот", "шестисот", "семисот", "восьмисот", "девятисот"]

def num_ru_gen(n, g="m"):
    n = int(n)
    if n < 0: return "минус " + num_ru_gen(-n,g)
    if n == 0: return _GU[0]
    out = []
    if n >= 1000000:
        q,n = divmod(n,1000000); out.append(num_ru_gen(q) + " " + ("миллиона" if q%10==1 and q%100!=11 else "миллионов"))
    if n >= 1000:
        q,n = divmod(n,1000); out.append(num_ru_gen(q,"f") + " " + ("тысячи" if q%10==1 and q%100!=11 else "тысяч"))
    if n >= 100: out.append(_GH[n//100]); n%=100
    if 10 <= n < 20: out.append(_GT[n-10]); n=0
    if n >= 20: out.append(_GD[n//10]); n%=10
    if n: out.append("одной" if n==1 and g=="f" else _GU[n])
    return " ".join(out)

def fraction_words(s, gen=False):
    a,b=s.replace(",", ".").split(".",1); b=b.rstrip("0") or "0"
    whole,part=int(a),int(b)
    denominators={1:("десятая","десятых"),2:("сотая","сотых"),3:("тысячная","тысячных"),4:("десятитысячная","десятитысячных"),5:("стотысячная","стотысячных"),6:("миллионная","миллионных")}
    if len(b) not in denominators: return num_ru(whole) + " запятая " + " ".join(num_ru(int(d)) for d in b)
    one,many=denominators[len(b)]
    if gen:
        return num_ru_gen(whole,"f") + " " + ("целой" if whole%10==1 and whole%100!=11 else "целых") + " " + num_ru_gen(part,"f") + " " + many
    return num_ru(whole,"f") + " " + plural(whole,"целая","целых","целых") + " " + num_ru(part,"f") + " " + plural(part,one,many,many)

FULL_UNITS = [
    (r"килокалори(?:я|и|й|ю|ями|ям|ях)", "f", "килокалория", "килокалории", "килокалорий", "килокалории"),
    (r"грамм(?:а|ов|ы|у|ами|ам|ах)?", "m", "грамм", "грамма", "граммов", "грамма"),
    (r"килограмм(?:а|ов|ы|у|ами|ам|ах)?", "m", "килограмм", "килограмма", "килограммов", "килограмма"),
    (r"минут(?:а|ы|у|ами|ам|ах)?", "f", "минута", "минуты", "минут", "минуты"),
    (r"час(?:а|ов|ы|у|ами|ам|ах)?", "m", "час", "часа", "часов", "часа"),
    (r"задач(?:а|и|у|ами|ам|ах)?", "f", "задача", "задачи", "задач", "задачи"),
    (r"пункт(?:а|ов|ы|у|ами|ам|ах)?", "m", "пункт", "пункта", "пунктов", "пункта"),
    (r"километр(?:а|ов|ы|у|ами|ам|ах)?", "m", "километр", "километра", "километров", "километра"),
    (r"процент(?:а|ов|ы|у|ами|ам|ах)?", "m", "процент", "процента", "процентов", "процента"),
]

def normalize_full_units(text):
    abbreviations={"ккал":"килокалорий","кг":"килограммов","гр":"граммов","г":"граммов","мин":"минут","ч":"часов","км":"километров","%":"процентов"}
    text=re.sub(r"(\d+(?:[.,]\d+)?)\s*(ккал|кг|гр|г|мин|ч|км|%)(?![А-Яа-яЁё])",lambda m:m.group(1)+" "+abbreviations[m.group(2).lower()],text,flags=re.I)
    for rx,g,one,few,many,gen_one in FULL_UNITS:
        pattern = r"(?<![\w:.,])(?:(около|до|более|менее|порядка|свыше)\s+)?(\d+(?:[.,]\d+)?)\s*(?:" + rx + r")(?![А-Яа-яЁё])"
        def sub(m, g=g,one=one,few=few,many=many,gen_one=gen_one):
            prefix,raw=m.group(1),m.group(2)
            n,words=_num_tok(raw)
            if n is None:
                return (prefix + " " + fraction_words(raw,True) if prefix else words) + " " + gen_one
            n=int(n)
            if prefix:
                unit = gen_one if n%10==1 and n%100!=11 else many
                return prefix + " " + num_ru_gen(n,g) + " " + unit
            return num_ru(n,g) + " " + plural(n,one,few,many)
        text=re.sub(pattern,sub,text,flags=re.I)
    return text

# ---------------- latin ----------------
LATIN = {'github': 'гитхаб', 'cursor': 'курсор', 'telegram': 'телеграм', 'todoist': 'тодоист', 'fatsecret': 'фэт сикрет', 'vercel': 'версел', 'api': 'эй пи ай', 'ci': 'си ай', 'cd': 'си ди', 'mac': 'мак', 'macbook': 'макбук', 'windows': 'виндоус', 'intel': 'интел', 'wi-fi': 'вай-фай', 'wifi': 'вай-фай', 'python': 'питон', 'docker': 'докер', 'react': 'реакт', 'next': 'некст', 'node': 'нод', 'pr': 'пул реквест', 'ok': 'окей', 'google': 'гугл', 'youtube': 'ютуб', 'jarvis': 'джарвис', 'git': 'гит', 'ui': 'ю ай', 'url': 'ю ар эл', 'json': 'джейсон', 'deploy': 'деплой', 'frontend': 'фронтенд', 'my': 'май', 'site': 'сайт', 'bot': 'бот', 'parser': 'парсер', 'project': 'проект', 'async': 'асинк', 'rag': 'раг', 'llm': 'эл эл эм', 'tg': 'тэ гэ', 'vpn': 'вэ пэ эн', 'backend': 'бэкенд', 'status': 'статус', 'readme': 'ридми', 'main': 'мейн', 'dev': 'дев'}


def extend_latin(words):
    """Add pronunciations for Latin words from config (``latin_words``: {"word": "слово"})."""
    for k, v in (words or {}).items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            LATIN[k.strip().lower()] = v.strip()
_TR = {"a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л",
       "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
       "y": "й", "z": "з"}

def _latin(m):
    w = m.group(0); k = w.lower()
    if k in LATIN: return LATIN[k]
    # CamelCase -> split
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", w) or [w]
    out = []
    for p in parts:
        pl = p.lower()
        if pl in LATIN: out.append(LATIN[pl]); continue
        s = pl.replace("sh", "ш").replace("ch", "ч").replace("th", "т").replace("oo", "у").replace("ee", "и").replace("ck", "к")
        out.append("".join(_TR.get(c, c) for c in s))
    return " ".join(out)

# ---------------- rewrites (logical stress at the end) ----------------
# Pronunciation, not spelling: «тесты» is said with a hard «т» — «тэсты».
_TEST_RE = re.compile(r"\b([Тт])ест(ы|ов|ами|ам|ах|ом|а|е|у)?\b")
PRONOUNCE_STRESS = {"тэст": "т+эст", "тэсты": "т+эсты", "тэстов": "т+эстов", "тэстами": "т+эстами", "тэстам": "т+эстам",
                    "тэстах": "т+эстах", "тэстом": "т+эстом", "тэста": "т+эста", "тэсте": "т+эсте", "тэсту": "т+эсту"}

def pronounce(text):
    return _TEST_RE.sub(lambda m: m.group(1) + "эст" + (m.group(2) or ""), text)

REWRITES = [
    (r"(^|[.!?]\s+)По данным на\s+", r"\1Данные на "),
    (r"Из проектов сегодня затрагивал(?:ись|ся|ось|ась)\s+следующие\s*:?", "Сегодня вы работали над проектами:"),
    (r"Из проектов сегодня затрагивал(?:ись|ся|ось|ась)", "Сегодня вы работали над"),
]

# ---------------- stress dictionary ----------------
# exact word forms (lowercase) -> stressed
STRESS_WORDS = {
    "белка": "белк+а", "белку": "белк+у", "белком": "белк+ом", "белков": "белк+ов", "белки": "белк+и", "белке": "белк+е",
    "репо": "р+епо", "логи": "л+оги", "логов": "л+огов", "на": "на", "сэр": "сэр", "данные": "д+анные", "данных": "д+анных",
    "пуш": "пуш", "пуша": "п+уша", "пуши": "п+уши", "запушил": "зап+ушил", "запушить": "зап+ушить", "пул": "пул", "пулл": "пулл",
    "сайт": "сайт", "сайта": "с+айта", "ноль": "ноль", "двадцать": "дв+адцать", "тридцать": "тр+идцать",
    "килограмм": "килогр+амм", "грамм": "грамм", "граммов": "гр+аммов", "грамма": "гр+амма",
    "звонок": "звон+ок", "звонки": "звонк+и", "звонков": "звонк+ов", "звонить": "звон+ить",
    "задача": "зад+ача", "задачи": "зад+ачи", "задач": "зад+ач", "задачу": "зад+ачу",
    "кэш": "кэш", "кэша": "к+эша", "кэше": "к+эше",
}
# v3.7: reviewed local conversational vocabulary; applied AFTER RUAccent.
# Explicit marks also invalidate the audio cache through the voice cache revision.
LOCAL_STRESS = {w.replace("+", ""): w for w in ['батар+ею', 'бес+еде', 'благодар+ю', 'б+удет', 'в+ашим', 'в+ечер', 'в+ижу', 'вр+емя', 'всегд+а', 'всег+о', 'встр+ечи', 'в+ышло', 'голосов+ой', 'гот+ово', 'д+атчик', 'д+елаю', 'дж+арвис', 'д+оброго', 'д+оброе', 'д+оброй', 'д+обрый', 'д+обрым', 'дов+ольны', 'запр+ос', 'здр+авствуйте', 'когд+а', 'к+урсор', 'л+адно', 'мин+уту', 'мог+у', 'над+еюсь', 'настро+ении', 'нач+ала', 'н+ашей', 'недост+упен', 'н+очи', 'ос+обенно', 'оста+юсь', 'отв+ет', '+отдыха', 'отпр+авить', 'повтор+ите', 'пож+алуйста', 'п+озже', 'получ+илось', 'пом+очь', 'пом+ощник', 'п+онял', 'попр+обуйте', 'пор+ядке', 'пост+авить', 'почт+и', 'прекр+асно', 'прик+ажете', 'прилож+ение', 'при+ятно', 'при+ятных', 'продолж+ается', 'про+ект', 'прост+ите', 'раб+очем', 'рассл+ышал', 'репозит+орий', 'свид+ания', 'св+язи', 'сд+елано', 'сейч+ас', 'сек+унду', 'с+ию', 'ск+ажете', 'ск+олько', 'сл+ушаю', 'сл+ушаюсь', 'сл+ышать', 'спок+ойной', 'стар+аюсь', 'т+аймер', 'температ+уры', 'уж+е', 'умолк+аю', 'усл+угам', 'уточн+яю', '+утро', '+утром', 'хор+ошего', 'хорош+о', 'пр+ежнему', 'догов+ор', 'позвон+ит', 'включ+ит', 'крас+ивее', 'т+орты', 'щав+ель', 'обесп+ечение', 'звонк+и', 'звон+ит', 'позвон+ят', 'св+ежих', 'д+анных', 'устар+ели', 'запр+ашиваю', 'мин+уты', 'мин+ута', 'мин+ут', 'час+а', 'час+ов', 'од+ин', 'одн+а', 'одн+у', 'д+евять', 'в+осемь', 'чет+ыре', 'од+иннадцать', 'двен+адцать', 'трин+адцать', 'чет+ырнадцать', 'пятн+адцать', 'шестн+адцать', 'семн+адцать', 'восемн+адцать', 'девятн+адцать', 'пятьдес+ят', 'шестьдес+ят', 'с+емьдесят', 'в+осемьдесят', 'девян+осто', 'дв+ести', 'тр+иста', 'чет+ыреста', 'пятьс+от', 'шестьс+от', 'семьс+от', 'восемьс+от', 'девятьс+от', 'т+ысяча', 'т+ысячи', 'т+ысяч', 'пол+овиной', 'р+овно', 'отмен+яю', 'блок+ирую', 'зап+исываю', 'зап+исано', 'пон+ятно', 'отм+ечу', 'отм+етил', 'в+ыполненным', 'сег+одняшнее', 'так+ой', '+это', 'в+ечера', 'акт+ивных', 'батар+еи', 'гр+адус', 'гр+адуса', 'гр+адусов', 'зар+яд', 'зар+ядка', 'настр+оен', 'подключен+а', 'пок+а', 'проц+ент', 'проц+ента', 'проц+ентов', 'раб+отаем', 'сист+емы', 'т+аймеров', 'температ+ура', '+этих']}
STRESS_WORDS.update(LOCAL_STRESS)

# Exact inflected status forms must take precedence over broad word stems.
STATUS_STRESS = {w.replace("+", ""): w for w in ['уточн+яю', 'уточн+яет', 'уточн+яют', 'уточн+яем', 'уточн+яете', 'уточн+ял', 'уточн+ю', 'календ+арь', 'календар+я', 'календар+ю', 'календар+е', 'календарём', 'календар+и', 'календар+ей', 'календар+ям', 'календар+ями', 'календар+ях', 'пят+идесяти', 'шест+идесяти', 'сем+идесяти', 'восьм+идесяти', 'сорок+а', 'девян+оста', 'ст+а', 'т+ысяч', 'т+ысячи', 'килокал+орий', 'килокал+ория', 'килокал+ории', 'килокал+орию', 'гр+амм', 'гр+амма', 'гр+аммов', 'белк+а', 'белк+ов', 'белк+и', 'зад+ача', 'зад+ачи', 'зад+ач', 'зад+ачу', 'зад+ачам', 'зад+ачами', 'зад+ачах', 'проср+очено', 'проср+очены', 'проср+оченных', 'ост+алось', 'ост+ались', 'заплан+ировано', 'заплан+ирован', 'заплан+ирована', 'комм+ит', 'комм+ита', 'комм+итов', 'депл+ой', 'депл+оя', 'депл+ою', 'депл+ое', 'ф+оно', 'пит+анию', 'соб+ытий', 'п+ункта', 'п+унктов', 'н+ормы', 'сег+одня', 'пят+и', 'шест+и', 'сем+и', 'восьм+и', 'девят+и', 'десят+и', 'од+иннадцати', 'двен+адцати', 'трин+адцати', 'чет+ырнадцати', 'пятн+адцати', 'шестн+адцати', 'семн+адцати', 'восемн+адцати', 'девятн+адцати', 'двадцат+и', 'тридцат+и', 'двухс+от', 'трёхс+от', 'четырёхс+от', 'пятис+от', 'шестис+от', 'семис+от', 'восьмис+от', 'девятис+от', 'одног+о', 'одн+ой', 'милли+она', 'милли+онов', 'сохранённые', 'обновл+яю', 'пров+еряю', 'гот+овится', 'св+ежие']}
STRESS_WORDS.update(STATUS_STRESS)
STRESS_WORDS["календарем"] = "календар+ем"
STRESS_WORDS.update(PRONOUNCE_STRESS)
STRESS_WORDS["слушаю"] = "сл+ушаю"

# stems: word must start with the stem, suffix <= 4 letters
STRESS_STEMS = [
    "фронт+енд", "б+экенд", "б+экэнд", "б+екенд", "депл+о", "задепл+о", "передепл+о", "комм+ит", "закомм+ит",
    "рекв+ест", "репозит+ори", "гитх+аб", "к+урсор", "телегр+ам", "тодо+ист", "календ+ар", "килокал+ори",
    "проср+оченн", "ст+атус", "рел+из", "прод+акшн", "прод+акшен", "интерф+ейс", "дашб+орд", "л+ендинг", "эндп+оинт",
    "воркфл+оу", "пайпл+айн", "д+окер", "п+итон", "джаваскр+ипт", "тайпскр+ипт", "р+еакт", "в+ерсел", "д+омен",
    "сб+орк", "м+ердж", "м+ерж", "в+етк", "ноутб+ук", "др+айвер", "обновл+ени", "тренир+овк", "апд+ейт", "апгр+ейд",
    "рефактор+инг", "р+ефактор", "мигр+аци", "серв+ис", "с+ервер", "кл+иент", "т+окен", "в+ебхук", "рут+ин", "безупр+ечн",
    "про+ект", "лог+ин", "пар+оль", "ск+риншот", "скр+иншот", "т+ест", "т+естир", "ф+икс", "ф+ичи", "ф+ича", "ф+ичу",
    "б+аг", "бр+аузер", "м+онитор", "экр+ан", "дизайн", "диз+айн", "верст+к", "бр+анч", "ворк+ер", "ч+екаут", "з+апуск",
    "отч+ёт", "отч+ет", "св+одк", "тел+еграм", "бот", "б+от", "инсталл+ер", "конф+иг", "п+акет", "п+лагин", "ж+урнал",
]
_STEMS = {}
def _build_stems(extra=None):
    d = {}
    for s in STRESS_STEMS + list(extra or []):
        k = s.replace("+", "").lower()
        if "+" in s: d[k] = s.index("+")
    return d
_STEMS = _build_stems()
_STEMS_SORTED = sorted(_STEMS, key=len, reverse=True)
_RX_STRESSED = {}

def _place(word, idx):
    return word[:idx] + "+" + word[idx:]

def _stress_word(w, words, stems, stems_sorted):
    plain = w.replace("+", "")
    lo = plain.lower().replace("ё", "е") if False else plain.lower()
    if lo in words:
        v = words[lo]
        if "+" not in v: return plain
        return _place(plain, v.index("+")) if len(v.replace("+", "")) == len(plain) else v
    for st in stems_sorted:
        if lo.startswith(st) and len(lo) - len(st) <= 4:
            return _place(plain, stems[st])
    return w

def apply_dict(text, cfg):
    words = dict(STRESS_WORDS)
    stems, stems_sorted = _STEMS, _STEMS_SORTED
    user = (cfg or {}).get("stress_dict", {}) or {}
    ustems = [v for k, v in user.items() if k.endswith("*")]
    for k, v in user.items():
        if not k.endswith("*"): words[k.lower()] = v
    if ustems:
        stems = dict(_STEMS); stems.update(_build_stems(ustems)); stems_sorted = sorted(stems, key=len, reverse=True)
    return re.sub(r"[А-Яа-яЁё+]+", lambda m: _stress_word(m.group(0), words, stems, stems_sorted), text)

# ---------------- RUAccent (optional) ----------------
_ACC = {"obj": None, "state": "off", "ms": None}
_ACC_LOCK = threading.Lock()


def _patch_sessions(obj, depth=0, seen=None):
    """transformers>=5 tokenizers drop token_type_ids; add zeros if the onnx model needs them."""
    import numpy as _np
    seen = seen if seen is not None else set()
    if depth > 3 or id(obj) in seen: return
    seen.add(id(obj))
    for name, v in list(getattr(obj, "__dict__", {}).items()):
        if type(v).__name__ == "InferenceSession":
            need = [i.name for i in v.get_inputs()]
            if "token_type_ids" in need and not getattr(v, "_jv_patched", False):
                orig = v.run
                def run(out_names, feed, *a, _orig=orig, **k):
                    if "token_type_ids" not in feed and "input_ids" in feed:
                        feed = dict(feed); feed["token_type_ids"] = _np.zeros_like(feed["input_ids"])
                    return _orig(out_names, feed, *a, **k)
                v.run = run; v._jv_patched = True
        elif hasattr(v, "__dict__") and not isinstance(v, (str, bytes, int, float)):
            _patch_sessions(v, depth + 1, seen)

def init_accentizer(cfg, base):
    if not cfg.get("stress_ruaccent", True):
        _ACC["state"] = "disabled"; return
    with _ACC_LOCK:
        if _ACC["obj"] is not None: return
        try:
            t0 = time.time()
            from ruaccent import RUAccent
            a = RUAccent()
            wd = os.path.join(base, "models", "ruaccent"); os.makedirs(wd, exist_ok=True)
            a.load(omograph_model_size=cfg.get("ruaccent_model", "turbo3.1"), use_dictionary=bool(cfg.get("ruaccent_dictionary", True)),
                   device="CPU", workdir=wd, tiny_mode=bool(cfg.get("ruaccent_tiny_mode", False)))
            _patch_sessions(a)
            a.process_all("прогрев модели ударений, замок на двери.")
            _ACC["obj"] = a; _ACC["state"] = "ready"
            log.info("ruaccent loaded in %.1fs (%s)", time.time() - t0, cfg.get("ruaccent_model", "turbo3.1"))
        except Exception as e:
            _ACC["state"] = "failed"; log.warning("ruaccent unavailable: %s", e)

def accent_state():
    return _ACC["state"]

def _ruaccent(text):
    a = _ACC["obj"]
    if a is None: return text
    try:
        t0 = time.time()
        out = " ".join(a.process_all(p) for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip())
        _ACC["ms"] = (time.time() - t0) * 1000
        log.info("ruaccent %.0f ms (%d chars)", _ACC["ms"], len(text))
        return out
    except Exception as e:
        log.warning("ruaccent failed: %s", e); return text

# ---------------- pipeline ----------------
def normalize(text, cfg=None, accent=True):
    cfg = cfg or {}
    t = text.replace("\u00a0", " ")
    for a, b in REWRITES + [tuple(x) for x in (cfg.get("phrase_rewrites") or [])]:
        try: t = re.sub(a, b, t)
        except re.error as e: log.warning("bad rewrite %r: %s", a, e)
    t = re.sub(r"[A-Za-z][A-Za-z\-]*[A-Za-z]|[A-Za-z]", _latin, t)
    # times: 22:06 / 22.06 after "на|в|к|до|с" / 22 06 after those prepositions
    t = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", lambda m: time_words(m.group(1), m.group(2)), t)
    t = re.sub(r"(?i)\b(на|в|к|до|с|после|около)\s+([01]?\d|2[0-3])[ .]([0-5]\d)\b",
               lambda m: f"{m.group(1)} {time_words(m.group(2), m.group(3))}", t)
    t = normalize_full_units(t)
    t = pronounce(t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*(ккал|кг|гр|г|мин|ч|км|%)(?![А-Яа-яЁё])", _units, t)
    t = re.sub(r"(\d+)[.,](\d+)", lambda m: _num_tok(m.group(0))[1], t)
    t = re.sub(r"\d+", lambda m: num_ru(m.group(0)), t)
    t = t.replace("—", ",").replace("–", ",").replace("«", "").replace("»", "").replace("\"", "")
    t = re.sub(r"\s+", " ", t).strip()
    if accent and _ACC["obj"] is not None: t = _ruaccent(t)
    t = apply_dict(t, cfg)
    return t
