"""Manage the local food alias cache used by «добавь 200 грамм творога».

    python scripts/food_alias.py --home <JARVIS_HOME> add --food-id 33692 --names творог,творога,творогу
    python scripts/food_alias.py --home <JARVIS_HOME> add --food-id 33792 --names яйцо,яйца,яиц --piece-g 50
    python scripts/food_alias.py --home <JARVIS_HOME> list

``add`` reads the food once from FatSecret (read-only food.get), picks its "100 g" (or
"100 ml") serving and stores per-unit calories and protein. Nothing is written to the diary.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import jarvis_food as FOOD  # noqa: E402


def metric_serving(food: Dict[str, Any], unit: str) -> Dict[str, Any]:
    s = (food.get("servings") or {}).get("serving", [])
    for x in s if isinstance(s, list) else [s]:
        if x.get("measurement_description") == unit and float(x.get("number_of_units") or 0) > 0:
            return x
    raise SystemExit("no per-%s serving for this food; pick another food_id" % unit)


def add(home: Path, args: argparse.Namespace, call) -> FOOD.FoodAlias:
    food = call("food.get", {"food_id": args.food_id}).get("food") or {}
    serving = metric_serving(food, "ml" if args.unit == "ml" else "g")
    n = float(serving["number_of_units"])
    names = [x.strip().lower() for x in args.names.split(",") if x.strip()]
    alias = FOOD.FoodAlias(tuple(names), str(args.food_id), str(serving["serving_id"]), args.label or names[0].capitalize(),
                           args.unit, round(float(serving.get("calories") or 0) / n, 4), round(float(serving.get("protein") or 0) / n, 4),
                           float(args.piece_g or 0))
    cache = FOOD.AliasCache(home / FOOD.DEFAULTS["food_alias_file"])
    items: List[FOOD.FoodAlias] = [a for a in cache.load() if a.food_id != alias.food_id]
    cache.save(items + [alias])
    print("saved %s -> %s (%s), %.2f kcal and %.2f g protein per %s" % (
        ",".join(alias.names), food.get("food_name"), alias.serving_id, alias.kcal_per_unit, alias.protein_per_unit, alias.unit))
    return alias


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", required=True, type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--food-id", required=True)
    a.add_argument("--names", required=True, help="comma-separated spoken forms")
    a.add_argument("--label", default="")
    a.add_argument("--unit", choices=("g", "ml"), default="g")
    a.add_argument("--piece-g", type=float, default=0)
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for x in FOOD.AliasCache(args.home / FOOD.DEFAULTS["food_alias_file"]).load():
            print(x.label, "|", ",".join(x.names), "|", x.food_id, x.serving_id, x.unit, x.piece_g or "")
        return 0
    import fatsecret_call
    add(args.home, args, fatsecret_call.call)
    return 0


if __name__ == "__main__":
    sys.exit(main())
