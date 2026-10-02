"""Build data/recipes.json from raw vanilla Minecraft data.

Source: InventivetalentDev/minecraft-assets, ref 1.21.11 -- the exact version
donut.auction serves. Two requests total:

  data/minecraft/recipe/_all.json        every recipe, raw vanilla format
  data/minecraft/tags/item/_all.json     every item tag

Keeps crafting_shaped and crafting_shapeless only. Tags are expanded to concrete
item names so a recipe asking for '#minecraft:planks' can be costed against
whichever plank is cheapest, rather than one arbitrary representative.

Run from the repo root:  python tools/build_recipes.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

REFS = ["1.21.11", "1.21.11-rc3", "1.21.11-rc2", "1.21.11-rc1", "1.21.10", "1.21.9"]
REPO = "InventivetalentDev/minecraft-assets"
RAW = f"https://raw.githubusercontent.com/{REPO}"
UA = {"User-Agent": "craftflip-recipe-builder/1.0"}

KEEP_TYPES = {"minecraft:crafting_shaped", "minecraft:crafting_shapeless"}
OUT_PATH = os.path.join("data", "recipes.json")


def fetch(ref: str, path: str):
    url = f"{RAW}/{ref}/{path}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()), url


def load_source():
    """Return (recipes, tags, ref, urls) from the first ref that has both files."""
    errors = []
    for ref in REFS:
        try:
            recipes, r_url = fetch(ref, "data/minecraft/recipe/_all.json")
            tags, t_url = fetch(ref, "data/minecraft/tags/item/_all.json")
            return recipes, tags, ref, [r_url, t_url]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ref}: {type(exc).__name__}: {exc}")
    raise SystemExit("no usable ref:\n  " + "\n  ".join(errors))


def strip_ns(name: str) -> str:
    return name.split(":", 1)[1] if name.startswith("minecraft:") else name


class TagResolver:
    """Expand item tags to concrete item names, recursively and cycle-safely."""

    def __init__(self, tags: dict):
        self.raw = {strip_ns(k): v for k, v in tags.items()}
        self.cache: dict[str, list[str]] = {}

    def resolve(self, tag: str, _seen: frozenset[str] = frozenset()) -> list[str]:
        name = strip_ns(tag)
        if name in self.cache:
            return self.cache[name]
        if name in _seen or name not in self.raw:
            return []
        out: list[str] = []
        for entry in self.raw[name].get("values", []):
            # entries are either "minecraft:foo" or {"id": "...", "required": false}
            ref = entry.get("id") if isinstance(entry, dict) else entry
            if not ref:
                continue
            if ref.startswith("#"):
                out.extend(self.resolve(ref, _seen | {name}))
            else:
                out.append(strip_ns(ref))
        deduped = sorted(set(out))
        self.cache[name] = deduped
        return deduped


def ingredient_spec(raw, resolver: TagResolver):
    """Normalise one recipe ingredient slot to {'item'|'tag'|'options'}.

    Vanilla 1.21.11 allows a bare string, {'item': ...}, {'tag': ...}, or a list of
    alternatives. Returns None when nothing usable is in it.
    """
    if isinstance(raw, list):
        opts: list[str] = []
        for sub in raw:
            got = ingredient_spec(sub, resolver)
            if not got:
                continue
            if "item" in got:
                opts.append(got["item"])
            elif "tag" in got:
                opts.extend(resolver.resolve(got["tag"]))
            else:
                opts.extend(got["options"])
        opts = sorted(set(opts))
        if not opts:
            return None
        if len(opts) == 1:
            return {"item": opts[0]}
        return {"options": opts}

    if isinstance(raw, str):
        return {"tag": strip_ns(raw[1:])} if raw.startswith("#") else {"item": strip_ns(raw)}

    if isinstance(raw, dict):
        if "item" in raw:
            return {"item": strip_ns(raw["item"])}
        if "tag" in raw:
            return {"tag": strip_ns(raw["tag"])}
    return None


def spec_key(spec: dict) -> tuple:
    for k in ("item", "tag", "options"):
        if k in spec:
            return (k, tuple(spec[k]) if k == "options" else spec[k])
    return ("?",)


def build(recipes: dict, tags: dict, ref: str, urls: list[str]):
    resolver = TagResolver(tags)
    out = []
    skipped_type = skipped_unresolved = 0

    for rid, rec in sorted(recipes.items()):
        rtype = rec.get("type", "")
        if rtype not in KEEP_TYPES:
            skipped_type += 1
            continue

        result = rec.get("result") or {}
        out_item = result.get("id") or (
            result.get("item") if isinstance(result.get("item"), str) else None
        )
        if not out_item:
            skipped_unresolved += 1
            continue

        cells: list[tuple[tuple[int, int], dict]] = []  # (row, col) -> spec

        if rtype == "minecraft:crafting_shaped":
            pattern = rec.get("pattern") or []
            key = rec.get("key") or {}
            for r, row in enumerate(pattern):
                for c, ch in enumerate(row):
                    if ch == " ":
                        continue
                    spec = ingredient_spec(key.get(ch), resolver)
                    if spec:
                        cells.append(((r, c), spec))
        else:  # crafting_shapeless
            for i, raw in enumerate(rec.get("ingredients") or []):
                spec = ingredient_spec(raw, resolver)
                if spec:
                    cells.append(((i, 0), spec))

        if not cells:
            skipped_unresolved += 1
            continue

        # A tag must actually resolve, or the recipe cannot be costed at all.
        if any(s.get("tag") and not resolver.resolve(s["tag"]) for _, s in cells):
            skipped_unresolved += 1
            continue

        grouped: dict[tuple, dict] = {}
        for (r, c), spec in cells:
            k = spec_key(spec)
            if k not in grouped:
                entry = dict(spec)
                entry["count"] = 0
                entry["grid"] = []
                grouped[k] = entry
            grouped[k]["count"] += 1
            # grid only carries real 2-D positions; shapeless slots have no shape
            if rtype == "minecraft:crafting_shaped":
                grouped[k]["grid"].append([r, c])

        out.append(
            {
                "id": rid,
                "type": rtype.replace("minecraft:", ""),
                "output": {"item": strip_ns(out_item), "count": int(result.get("count", 1))},
                "ingredients": list(grouped.values()),
            }
        )

    doc = {
        "sourceUrl": urls,
        "sourceRepo": REPO,
        "mcVersion": ref,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "tools/build_recipes.py",
        "counts": {
            "recipes": len(out),
            "distinctOutputs": len({r["output"]["item"] for r in out}),
            "distinctIngredientItems": len(
                {
                    n
                    for r in out
                    for ing in r["ingredients"]
                    for n in ([ing["item"]] if "item" in ing else ing.get("options", []))
                }
            ),
            "distinctTags": len({i["tag"] for r in out for i in r["ingredients"] if "tag" in i}),
            "skippedNonCrafting": skipped_type,
            "skippedUnresolved": skipped_unresolved,
        },
        "recipes": out,
    }
    body = json.dumps(doc, separators=(",", ":"), sort_keys=False)
    doc["sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return doc


def main() -> int:
    recipes, tags, ref, urls = load_source()
    print(f"source ref {ref}: {len(recipes)} recipes, {len(tags)} item tags")
    doc = build(recipes, tags, ref, urls)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    print("wrote", OUT_PATH, "->", json.dumps(doc["counts"]))
    print("sha256", doc["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
