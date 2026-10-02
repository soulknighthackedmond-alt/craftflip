"""Tests for the flip engine. Pure arithmetic over a stub market -- no network.

Run either way:
  python tests/test_flips.py          (plain, no pytest needed)
  python -m pytest tests -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.flips import compute_flip, ingredient_options, needed_names  # noqa: E402
from app.market import candidate_tokens, plain_entry  # noqa: E402


class StubMarket:
    """Only .lookup() is used by compute_flip."""

    def __init__(self, index: dict):
        self.index = index

    def lookup(self, name):
        return self.index.get(name)


def entry(market_value=None, listing=None):
    return {
        "itemId": f"id-{market_value}-{listing}",
        "itemName": "x",
        "displayName": None,
        "marketValue": market_value,
        "volume24h": 0.0,
        "sales24h": 0.0,
        "cheapestListing": None if listing is None else {"unitPrice": listing, "observedAt": "2026-10-02T00:00:00Z"},
    }


def recipe(ingredients, output_item="out", output_count=1, rid="r"):
    return {
        "id": rid,
        "type": "crafting_shaped",
        "output": {"item": output_item, "count": output_count},
        "ingredients": ingredients,
    }


def item(name, count=1):
    return {"item": name, "count": count, "grid": [[0, 0]]}


# --------------------------------------------------------------- cost side ----

def test_cost_uses_cheapest_live_listing():
    market = StubMarket({"a": entry(market_value=100, listing=50), "out": entry(market_value=500)})
    flip = compute_flip(recipe([item("a", 4)]), market)
    assert flip is not None
    assert flip["cost"] == 200, flip["cost"]
    assert flip["ingredients"][0]["source"] == "listing"
    assert flip["estimated"] is False


def test_cost_falls_back_to_market_value_and_flags_estimated():
    market = StubMarket({"a": entry(market_value=100, listing=None), "out": entry(market_value=500)})
    flip = compute_flip(recipe([item("a", 2)]), market)
    assert flip is not None
    assert flip["cost"] == 200
    assert flip["ingredients"][0]["source"] == "market"
    assert flip["estimated"] is True


def test_listing_beats_market_value_even_when_higher():
    # you buy at the listing price, not the average sale -- even if it is worse
    market = StubMarket({"a": entry(market_value=10, listing=99), "out": entry(market_value=1000)})
    flip = compute_flip(recipe([item("a", 1)]), market)
    assert flip["cost"] == 99


# --------------------------------------------------------------- tag side ----

def test_tag_resolves_to_cheapest_member():
    market = StubMarket(
        {
            "oak_planks": entry(market_value=40, listing=40),
            "birch_planks": entry(market_value=12, listing=12),
            "spruce_planks": entry(market_value=25, listing=25),
            "out": entry(market_value=500),
        }
    )
    ing = {"tag": "planks", "count": 4, "options": ["oak_planks", "birch_planks", "spruce_planks"], "grid": []}
    flip = compute_flip(recipe([ing]), market)
    assert flip is not None
    assert flip["ingredients"][0]["item"] == "birch_planks"
    assert flip["cost"] == 48
    assert flip["ingredients"][0]["via"] == "planks"
    assert flip["ingredients"][0]["optionsConsidered"] == 3


def test_tag_skips_members_with_no_price():
    market = StubMarket({"spruce_planks": entry(market_value=25, listing=25), "out": entry(market_value=500)})
    ing = {"tag": "planks", "count": 2, "options": ["oak_planks", "spruce_planks"], "grid": []}
    flip = compute_flip(recipe([ing]), market)
    assert flip["ingredients"][0]["item"] == "spruce_planks"


# ------------------------------------------------------------- skip rules ----

def test_recipe_with_an_unpriced_leg_is_skipped():
    market = StubMarket({"a": entry(market_value=10, listing=10), "out": entry(market_value=500)})
    flip = compute_flip(recipe([item("a", 1), item("unobtainium", 1)]), market)
    assert flip is None


def test_recipe_with_unpriced_output_is_skipped():
    market = StubMarket({"a": entry(market_value=10, listing=10)})
    assert compute_flip(recipe([item("a", 1)], output_item="nowhere"), market) is None


def test_recipe_whose_only_ingredient_is_free_is_skipped():
    market = StubMarket({"a": entry(market_value=0, listing=0), "out": entry(market_value=500)})
    assert compute_flip(recipe([item("a", 1)]), market) is None


# ----------------------------------------------------------- revenue side ----

def test_revenue_uses_market_value_times_output_count():
    market = StubMarket({"a": entry(market_value=10, listing=10), "out": entry(market_value=100)})
    flip = compute_flip(recipe([item("a", 1)], output_count=4), market)
    assert flip["revenue"] == 400
    assert flip["outputCount"] == 4


def test_revenue_falls_back_to_listing_when_no_market_value():
    market = StubMarket({"a": entry(market_value=10, listing=10), "out": entry(market_value=None, listing=70)})
    flip = compute_flip(recipe([item("a", 1)]), market)
    assert flip["revenue"] == 70
    assert flip["output"]["source"] == "listing"


# ----------------------------------------------------------- profit maths ----

def test_profit_and_margin():
    market = StubMarket({"a": entry(market_value=10, listing=100), "out": entry(market_value=1000)})
    flip = compute_flip(recipe([item("a", 1)]), market)
    assert flip["cost"] == 100
    assert flip["revenue"] == 1000
    assert flip["profit"] == 900
    assert abs(flip["margin"] - 9.0) < 1e-9


def test_fee_is_taken_off_revenue():
    market = StubMarket({"a": entry(market_value=10, listing=100), "out": entry(market_value=1000)})
    flip = compute_flip(recipe([item("a", 1)]), market, fee_percent=5.0)
    assert flip["fee"] == 50
    assert flip["profit"] == 850


def test_loss_is_negative_and_flagged():
    market = StubMarket({"a": entry(market_value=10, listing=900), "out": entry(market_value=100)})
    flip = compute_flip(recipe([item("a", 1)]), market)
    assert flip["profit"] < 0
    assert flip["margin"] < 0
    assert flip["listedNow"] is None


def test_listed_now_carries_the_output_listing():
    market = StubMarket({"a": entry(market_value=10, listing=10), "out": entry(market_value=100, listing=140)})
    flip = compute_flip(recipe([item("a", 1)]), market)
    assert flip["listedNow"] == 140
    assert flip["listedAt"] == "2026-10-02T00:00:00Z"


# ------------------------------------------------------------- dataset glue ----

def test_ingredient_options_covers_item_tag_and_list():
    assert ingredient_options({"item": "oak_planks"}) == ["oak_planks"]
    assert ingredient_options({"tag": "planks", "options": ["a", "b"]}) == ["a", "b"]


def test_needed_names_includes_outputs_and_every_tag_member():
    recipes = [recipe([{"tag": "planks", "count": 1, "options": ["oak_planks", "birch_planks"], "grid": []}])]
    assert needed_names(recipes) == {"out", "oak_planks", "birch_planks"}


# ------------------------------------------------------------------ market ----

def test_plain_entry_prefers_the_unmodified_item():
    entries = [
        {"item": {"itemName": "netherite_axe", "enchantments": [], "displayName": "\u00a7bGod Axe"}, "price": {"value": 8330731}},
        {"item": {"itemName": "netherite_axe", "enchantments": [], "displayName": None}, "price": {"value": 5593000}},
    ]
    picked = plain_entry(entries, "netherite_axe")
    assert picked["price"]["value"] == 5593000


def test_plain_entry_ignores_enchantments():
    entries = [
        {"item": {"itemName": "diamond_sword", "enchantments": [{"name": "sharpness", "level": 5}], "displayName": None}},
        {"item": {"itemName": "diamond_sword", "enchantments": [], "displayName": None}},
    ]
    picked = plain_entry(entries, "diamond_sword")
    assert picked["item"]["enchantments"] == []


def test_plain_entry_returns_none_when_name_absent():
    assert plain_entry([{"item": {"itemName": "other", "enchantments": [], "displayName": None}}], "wanted") is None


def test_candidate_tokens_are_substrings_covering_several_names():
    toks = candidate_tokens({"oak_planks", "birch_planks", "spruce_planks", "netherite_ingot"})
    assert "planks" in toks
    assert toks[0] == "planks"  # covers three names, so it is tried first
    # a token covering one name is left to the per-name fallback
    assert "netherite_ingot" not in toks


# ------------------------------------------------------------------ table ----

def test_actionable_requires_every_material_listed():
    market = StubMarket(
        {"a": entry(market_value=10, listing=10), "b": entry(market_value=5, listing=None), "out": entry(market_value=500)}
    )
    both = compute_flip(recipe([item("a", 1)]), market)
    mixed = compute_flip(recipe([item("a", 1), item("b", 1)]), market)
    assert both["actionable"] is True
    assert both["estimated"] is False
    assert mixed["actionable"] is False
    assert mixed["estimated"] is True
    assert (mixed["materialsListed"], mixed["materialsTotal"]) == (1, 2)


def test_dedupe_keeps_one_row_per_output_preferring_actionable():
    from app.flips import FlipTable

    estimated = {"item": "x", "actionable": False, "profit": 9000.0, "alternates": 0}
    buyable = {"item": "x", "actionable": True, "profit": 100.0, "alternates": 0}
    rows = FlipTable._dedupe([estimated, buyable])
    assert len(rows) == 1
    assert rows[0]["actionable"] is True
    assert rows[0]["alternates"] == 1


def test_dedupe_prefers_higher_profit_within_the_same_actionability():
    from app.flips import FlipTable

    low = {"item": "x", "actionable": True, "profit": 100.0, "alternates": 0}
    high = {"item": "x", "actionable": True, "profit": 500.0, "alternates": 0}
    rows = FlipTable._dedupe([low, high])
    assert len(rows) == 1 and rows[0]["profit"] == 500.0


def test_dedupe_drops_uncomputable_recipes():
    from app.flips import FlipTable

    assert FlipTable._dedupe([None, None]) == []


# ---------------------------------------------------------------- the runner ----

def _run() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
