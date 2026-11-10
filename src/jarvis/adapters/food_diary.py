"""Local food logging that touches the outside: the alias cache file, the FatSecret diary and a journal.

The diary talks to FatSecret through an injected ``call(method, params)``
(jarvis.adapters.fatsecret.call in production, a fake in tests). Every write reads the diary
before and after, is never retried blindly and is journaled locally, so a repeated voice
command or a transport error cannot create duplicate entries.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from jarvis.core.food import (DEFAULTS, UNIT_WORDS, FoodAlias, FoodRequest, FoodResult, alias_from_dict, alias_to_dict, entries_of,
                              epoch_day, find_created, fmt, meal_for, name_score, norm, parse, remaining_clause, totals, units_for)

log = logging.getLogger("jarvis")
FatSecretCall = Callable[[str, Dict[str, Any]], Dict[str, Any]]


class AliasCache:
    """Small local mapping from spoken food names to one FatSecret food and serving."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path); self._lock = threading.Lock(); self._mtime: Optional[float] = None
        self.items: List[FoodAlias] = []

    def load(self) -> List[FoodAlias]:
        try:
            m = self.path.stat().st_mtime
        except OSError:
            self.items, self._mtime = [], None; return self.items
        if m == self._mtime:
            return self.items
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.items = [alias_from_dict(x) for x in data.get("foods", [])]
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("food alias cache unreadable (%s)", type(e).__name__); self.items = []
        self._mtime = m
        return self.items

    def save(self, items: List[FoodAlias]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps({"version": 1, "foods": [alias_to_dict(a) for a in items]}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, self.path); self._mtime = None

    def find(self, food: str) -> Optional[FoodAlias]:
        key = norm(food)
        scored = sorted(((name_score(key, a), i) for i, a in enumerate(self.load())), reverse=True)
        if not scored or scored[0][0] < 0.8:
            return None
        if len(scored) > 1 and scored[1][0] > scored[0][0] - 0.1:
            return None
        return self.items[scored[0][1]]


class Diary:
    def __init__(self, call: FatSecretCall) -> None:
        self.call = call

    def entries(self, day: int) -> List[Dict[str, Any]]:
        return entries_of(self.call("food_entries.get", {"date": str(day)}))

    def create(self, alias: FoodAlias, units: float, meal: str, day: int) -> str:
        r = self.call("food_entry.create", {"food_id": alias.food_id, "serving_id": alias.serving_id,
                                            "number_of_units": ("%.3f" % units).rstrip("0").rstrip("."), "meal": meal,
                                            "food_entry_name": alias.label, "date": str(day)})
        if "error" in r:
            raise RuntimeError("fatsecret_create_rejected")
        return str((r.get("food_entry_id") or {}).get("value", "") if isinstance(r.get("food_entry_id"), dict) else r.get("food_entry_id", ""))


class Journal:
    """Recent local writes; protects against the same voice command logged twice."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path); self.clock = clock; self._lock = threading.Lock()

    def _read(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def recent(self, food_id: str, units: float, window_s: float) -> bool:
        now = self.clock()
        return any(r.get("food_id") == food_id and abs(float(r.get("units", -1)) - units) < 1e-6 and now - float(r.get("at", 0)) < window_s
                   for r in self._read())

    def add(self, food_id: str, units: float, entry_id: str) -> None:
        with self._lock:
            rows = [r for r in self._read() if self.clock() - float(r.get("at", 0)) < 86400][-49:]
            rows.append({"at": self.clock(), "food_id": food_id, "units": units, "entry_id": entry_id})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(rows), encoding="utf-8"); os.replace(tmp, self.path)


class FoodLogger:
    def __init__(self, home: Path, call: FatSecretCall, cfg: Mapping[str, Any],
                 now: Callable[[], datetime.datetime] = datetime.datetime.now, clock: Callable[[], float] = time.time) -> None:
        self.home = Path(home); self.cfg = cfg; self.now = now
        self.cache = AliasCache(self.home / str(cfg.get("food_alias_file") or DEFAULTS["food_alias_file"]))
        self.diary = Diary(call); self.journal = Journal(self.home / "cache" / "food_journal.json", clock)

    def log_text(self, text: str) -> FoodResult:
        req = parse(text)
        return self.log(req) if req else FoodResult("ambiguous", reason="unparsed")

    def log(self, req: FoodRequest) -> FoodResult:
        alias = self.cache.find(req.food)
        if alias is None:
            return FoodResult("ambiguous", reason="unknown_food")
        units = units_for(req, alias)
        grams = units if alias.unit == "g" else None
        if units is None or units <= 0 or (grams is not None and grams > float(self.cfg.get("food_max_grams", 3000))):
            return FoodResult("ambiguous", reason="amount")
        if self.journal.recent(alias.food_id, units, float(self.cfg.get("food_dedupe_s", 180))):
            return FoodResult("duplicate", "Это уже записано, сэр.", reason="journal")
        now = self.now(); day = epoch_day(now.date()); meal = req.meal or meal_for(now)
        try:
            before = self.diary.entries(day)
        except Exception as e:  # nothing written yet: the server may still log it
            log.warning("food diary read failed before write (%s)", type(e).__name__)
            return FoodResult("unavailable", reason=type(e).__name__)
        entry_id = ""
        try:
            entry_id = self.diary.create(alias, units, meal, day)
        except Exception as e:
            log.warning("food create failed (%s); reading back instead of retrying", type(e).__name__)
        try:
            after = self.diary.entries(day)
        except Exception:
            return FoodResult("failed", "Не уверен, что запись прошла, сэр. Проверьте дневник.", reason="readback")
        entry = find_created(before, after, alias, units, entry_id)
        if entry is None:
            return FoodResult("failed", "Не удалось записать в дневник, сэр.", reason="not_created")
        entry_id = str(entry.get("food_entry_id", entry_id))
        self.journal.add(alias.food_id, units, entry_id)
        log.info("food logged locally food_id=%s units=%s meal=%s entry=%s", alias.food_id, units, meal, entry_id)
        spoken = ("Записал: " + alias.label.lower() + ", " + fmt(units) + " " + UNIT_WORDS[alias.unit] + ". " +
                  fmt(entry.get("calories")) + " килокалорий, " + fmt(entry.get("protein")) + " грамм белка. " +
                  remaining_clause(totals(after), self.cfg))
        return FoodResult("logged", spoken.strip(), entry_id=entry_id)

    def remaining(self, focus: str = "protein") -> str:
        t = totals(self.diary.entries(epoch_day(self.now().date())))
        targets = self.cfg.get("nutrition_targets") or {}
        eaten = "Сегодня " + fmt(t["protein"]) + " грамм белка и " + fmt(t["calories"]) + " килокалорий."
        return (eaten + " " + remaining_clause(t, self.cfg, focus)).strip() if targets else eaten[:-1] + ", сэр."
