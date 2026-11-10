"""Local food logging, pure part: «добавь 200 грамм творога» parsed, matched and spoken.

The diary, alias cache and journal that touch disk and FatSecret live in
jarvis.adapters.food_diary. Anything the cache cannot resolve unambiguously goes to the
server as ``food_log``.
"""
from __future__ import annotations

import datetime
import difflib
import logging
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from jarvis.core import numbers as NUMBERS
from jarvis.core.fold import fold

log = logging.getLogger("jarvis")

DEFAULTS: Dict[str, Any] = {
    "food_local_enabled": False, "food_alias_file": "cache/food_aliases.json",
    "food_dedupe_s": 180, "food_max_grams": 3000, "nutrition_targets": {},
}
PHRASES = ["сколько осталось до нормы белка", "сколько осталось белка", "сколько осталось калорий"]
MEALS = {"завтрак": "breakfast", "обед": "lunch", "ужин": "dinner", "перекус": "other"}
UNITS = [(r"килограмм\w*|кило|кг", "g", 1000.0), (r"грамм\w*|гр|г", "g", 1.0), (r"литр\w*|л", "ml", 1000.0),
         (r"миллилитр\w*|мл", "ml", 1.0), (r"штук\w*|шт|штучк\w*", "pc", 1.0)]
_VERB = re.compile(r"^(?:добавь|запиши|внеси)(?: (?:в дневник(?: питания)?|в фатсекрет|в еду|в питание|съел|я съел))? ")
_MEAL = re.compile(r" (?:на|в|к) (завтрак|обед|ужин|перекус)$")
_LEFT = re.compile(r"сколько (?:мне )?(?:еще )?(?:осталось|остается|не хватает)(?: (?:съесть|добрать))?(?: до норм[аы])?(?: (?:по )?(?P<a>белк\w*|протеин\w*|калори\w*|ккал))?"
                   r"|сколько (?P<b>белк\w*|калори\w*) (?:мне )?(?:еще )?(?:осталось|не хватает)(?: до нормы)?")
FATSECRET_MEALS = ("breakfast", "lunch", "dinner", "other")


@dataclass(frozen=True)
class FoodRequest:
    amount: float
    unit: str  # g, ml or pc
    food: str
    meal: Optional[str] = None


@dataclass(frozen=True)
class FoodAlias:
    names: Tuple[str, ...]
    food_id: str
    serving_id: str
    label: str
    unit: str = "g"  # what number_of_units counts for this serving: g, ml or pc
    kcal_per_unit: float = 0.0
    protein_per_unit: float = 0.0
    piece_g: float = 0.0


@dataclass
class FoodResult:
    status: str  # logged, duplicate, ambiguous, unavailable, failed
    spoken: str = ""
    reason: str = ""
    entry_id: str = ""


def norm(t: str) -> str:
    return " ".join(re.sub(r"[^\w\s.,]", " ", fold(str(t))).split())


def _split_amount(tokens: List[str], number: Callable[[str], Optional[float]]) -> Tuple[Optional[float], List[str]]:
    if tokens and tokens[0] in ("полкило", "пол кило"):
        return 500.0, ["г"] + tokens[1:]
    best = None
    for n in range(1, min(len(tokens), 4) + 1):
        v = number(" ".join(tokens[:n]))
        if v is not None:
            best = (v, n)
    return (best[0], tokens[best[1]:]) if best else (None, tokens)


def _split_unit(tokens: List[str]) -> Tuple[Optional[Tuple[str, float]], List[str]]:
    if tokens:
        for rx, unit, factor in UNITS:
            if re.fullmatch(rx, tokens[0].rstrip(".")):
                return (unit, factor), tokens[1:]
    return None, tokens


def parse(text: str, number: Optional[Callable[[str], Optional[float]]] = None) -> Optional[FoodRequest]:
    """One item with an amount; None for anything that needs the server (several items, no amount)."""
    number = number or NUMBERS.number
    t = norm(text)
    m = _VERB.match(t + " ")
    if not m:
        return None
    rest = t[m.end():].strip()
    meal = None
    mm = _MEAL.search(" " + rest)
    if mm:
        meal = MEALS[mm.group(1)]; rest = (" " + rest)[:mm.start()].strip()
    if not rest or re.search(r"(?:^| )(?:и|плюс)(?: |$)|,(?!\d)", rest):
        return None
    tokens = rest.split()
    amount, tail = _split_amount(tokens, number)
    if amount is None:  # «добавь творог 200 грамм»
        for i in range(1, len(tokens)):
            amount, tail2 = _split_amount(tokens[i:], number)
            if amount is not None:
                unit, after = _split_unit(tail2)
                if after:
                    return None
                return _request(amount, unit, " ".join(tokens[:i]), meal)
        return None
    unit, food = _split_unit(tail)
    return _request(amount, unit, " ".join(food), meal) if food else None


def _request(amount: float, unit: Optional[Tuple[str, float]], food: str, meal: Optional[str]) -> Optional[FoodRequest]:
    if amount <= 0 or not food:
        return None
    name, factor = unit or ("pc", 1.0)
    return FoodRequest(round(amount * factor, 3), name, food, meal)


def name_score(key: str, alias: FoodAlias) -> float:
    best = 0.0
    for name in alias.names:
        n = norm(name)
        if key == n:
            return 1.0
        prefix = len(os.path.commonprefix([key, n]))
        stem = 0.9 if prefix >= max(4, len(n) - 2) and abs(len(key) - len(n)) <= 3 else 0.0
        best = max(best, stem, difflib.SequenceMatcher(None, key, n).ratio())
    return best


def alias_from_dict(x: Dict[str, Any]) -> FoodAlias:
    names = tuple(str(n) for n in x["names"] if str(n).strip())
    if not names or x.get("unit", "g") not in ("g", "ml", "pc"):
        raise ValueError("bad_alias")
    return FoodAlias(names, str(x["food_id"]), str(x["serving_id"]), str(x.get("label") or names[0]), x.get("unit", "g"),
                     float(x.get("kcal_per_unit") or 0), float(x.get("protein_per_unit") or 0), float(x.get("piece_g") or 0))


def alias_to_dict(a: FoodAlias) -> Dict[str, Any]:
    return {"names": list(a.names), "food_id": a.food_id, "serving_id": a.serving_id, "label": a.label, "unit": a.unit,
            "kcal_per_unit": a.kcal_per_unit, "protein_per_unit": a.protein_per_unit, "piece_g": a.piece_g}


def units_for(req: FoodRequest, alias: FoodAlias) -> Optional[float]:
    """number_of_units for the alias serving, or None when the conversion would be a guess."""
    if req.unit == alias.unit:
        return req.amount
    if req.unit == "pc" and alias.unit == "g" and alias.piece_g > 0:
        return round(req.amount * alias.piece_g, 1)
    return None


def meal_for(now: datetime.datetime) -> str:
    h = now.hour
    return "breakfast" if 4 <= h < 11 else "lunch" if h < 16 else "dinner" if h < 22 else "other"


def epoch_day(day: datetime.date) -> int:
    return (day - datetime.date(1970, 1, 1)).days


def dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v or "0"))
    except InvalidOperation:
        return Decimal(0)


def entries_of(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "error" in response:
        raise RuntimeError("fatsecret_error_" + str((response.get("error") or {}).get("code", "")))
    e = (response.get("food_entries") or {}).get("food_entry", [])
    return e if isinstance(e, list) else [e]


def totals(entries: List[Dict[str, Any]]) -> Dict[str, Decimal]:
    return {k: sum((dec(x.get(k)) for x in entries), Decimal(0)) for k in ("calories", "protein")}


def fmt(v: Any) -> str:
    d = dec(v)
    return str(int(d.to_integral_value())) if abs(d) >= 10 or d == d.to_integral_value() else str(d.quantize(Decimal("0.1"))).replace(".", ",")


UNIT_WORDS = {"g": "грамм", "ml": "миллилитров", "pc": "штук"}


def remaining_clause(t: Dict[str, Decimal], cfg: Mapping[str, Any], focus: str = "protein") -> str:
    targets = cfg.get("nutrition_targets") or {}
    p_goal, k_goal = dec(targets.get("protein_g")), dec(targets.get("calories"))
    if not p_goal and not k_goal:
        return ""
    parts = []
    order = [("protein", p_goal), ("calories", k_goal)]
    if focus == "calories":
        order.reverse()
    for kind, goal in order:
        if not goal:
            continue
        left = goal - t[kind]
        word = "белка" if kind == "protein" else "калорий"
        unit = " грамм" if kind == "protein" else " килокалорий"
        parts.append("норма " + word + " выполнена" if left <= 0 else "до нормы " + word + " " + fmt(left) + unit)
    text = ", ".join(parts)
    return text[:1].upper() + text[1:] + ", сэр."


def find_created(before: List[Dict[str, Any]], after: List[Dict[str, Any]], alias: FoodAlias, units: float,
                 entry_id: str) -> Optional[Dict[str, Any]]:
    if entry_id:
        for e in after:
            if str(e.get("food_entry_id")) == entry_id:
                return e
    old = {str(e.get("food_entry_id")) for e in before}
    for e in after:
        if str(e.get("food_entry_id")) not in old and str(e.get("food_id")) == alias.food_id and abs(float(dec(e.get("number_of_units"))) - units) < 0.01:
            return e
    return None


def match(t: str, cfg: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Local «сколько осталось до нормы белка»; only when local food logging is enabled."""
    if not cfg.get("food_local_enabled"):
        return None
    m = _LEFT.fullmatch(t)
    if not m:
        return None
    word = m.group("a") or m.group("b") or ""
    return {"name": "quick_nutrition_left", "action": "quick2", "cmd": "nutrition_left",
            "focus": "calories" if word.startswith(("калори", "ккал")) else "protein"}
