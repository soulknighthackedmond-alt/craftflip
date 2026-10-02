"""Tests for the flip engine. Pure arithmetic over a stub market -- no network.

Run either way:
  python tests/test_flips.py          (plain, no pytest needed)
  python -m pytest tests -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.donut import sale_row, summarise_sales  # noqa: E402
from app.flips import SORTS, compute_flip, ingredient_options, needed_names  # noqa: E402
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


# --------------------------------------------------------- transaction feed ----

def test_sale_row_reads_the_real_upstream_shape():
    """Regression: the feed nests seller as an object and stamps timeSold. The
    earlier mapping read a flat `seller` and a `createdAt`, so both columns
    rendered a dash."""
    row = sale_row(
        {
            "seller": {"uuid": "d8d3-4a", "name": "noamgr17"},
            "price": 4700000,
            "timeSold": "2026-09-29T09:19:10.147Z",
            "itemId": "e5bce2cd",
            "itemCount": 1,
        }
    )
    assert row["seller"] == "noamgr17"
    assert row["at"] == "2026-09-29T09:19:10.147Z"
    assert row["price"] == 4700000
    assert row["unitPrice"] == 4700000


def test_sale_row_divides_a_stack_into_a_unit_price():
    row = sale_row({"seller": {"name": "x"}, "price": 6400, "itemCount": 64, "timeSold": "2026-10-01T00:00:00Z"})
    assert row["unitPrice"] == 100
    assert row["itemCount"] == 64


def test_sale_row_survives_a_missing_seller_and_count():
    row = sale_row({"price": 500})
    assert row["seller"] is None
    assert row["at"] is None
    assert row["itemCount"] == 1
    assert row["unitPrice"] == 500


def test_summarise_sales_reports_low_median_high_and_newest():
    sales = [
        sale_row({"price": 300, "timeSold": "2026-10-01T00:00:00Z"}),
        sale_row({"price": 100, "timeSold": "2026-09-01T00:00:00Z"}),
        sale_row({"price": 200, "timeSold": "2026-09-15T00:00:00Z"}),
    ]
    s = summarise_sales(sales)
    assert (s["low"], s["median"], s["high"]) == (100, 200, 300)
    # newest is by timestamp, not by position in the feed
    assert s["last"] == 300
    assert s["lastAt"] == "2026-10-01T00:00:00Z"


def test_summarise_sales_handles_an_empty_feed():
    assert summarise_sales([]) == {"sales": 0, "priced": 0}


def test_summarise_sales_ignores_unpriced_rows():
    sales = [sale_row({"price": 100, "timeSold": "2026-10-01T00:00:00Z"}), sale_row({"price": None})]
    s = summarise_sales(sales)
    assert s["sales"] == 2
    assert s["priced"] == 1
    assert s["median"] == 100


# ------------------------------------------------------- instasell (/sell) ----

class StubSellPrices:
    """Stand-in for SellPrices: item -> fixed /sell payout."""

    def __init__(self, payouts: dict[str, float], source: str = "in-game", base: dict | None = None):
        self._payouts = payouts
        self._source = source
        self._base = base or {}
        self.revision = 1

    def lookup(self, name):
        payout = self._payouts.get(name)
        if payout is None:
            return None
        return {
            "base": self._base.get(name, payout),
            "multiplier": 1.0,
            "payout": payout,
            "source": self._source,
            "note": None,
        }

    def payout(self, name):
        return self._payouts.get(name)


class StubSales:
    """Stand-in for SalesIndex: item -> median price it recently sold at."""

    def __init__(self, medians: dict[str, float]):
        self.basis = "median of recent sales"
        self._medians = medians
        self.revision = 1

    def entry(self, name):
        median = self._medians.get(name)
        if median is None:
            return None
        return {
            "low": median * 0.5,
            "median": median,
            "high": median * 2.0,
            "sales": 3,
            "lastAt": "2026-10-01T00:00:00Z",
        }

    def price(self, name):
        return self._medians.get(name)


def test_instasell_uses_the_fixed_sell_price_not_the_market():
    """The server's payout is what you get instantly; it ignores what players pay."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)], output_count=2),
        market,
        sales=StubSales({"out": 400}),
        sell_prices=StubSellPrices({"out": 250}),
    )
    assert flip["instasellUnitPrice"] == 250  # the /sell payout, not the 400 sale
    assert flip["instasellRevenue"] == 500
    assert flip["instasellProfit"] == 400  # 500 - 100
    assert flip["instasellBasis"] == "server /sell base price"
    assert flip["instasellSource"] == "in-game"


def test_instasell_keeps_the_market_dump_as_a_separate_number():
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)], output_count=2),
        market,
        sales=StubSales({"out": 400}),
        sell_prices=StubSellPrices({"out": 250}),
    )
    assert flip["dumpUnitPrice"] == 400
    assert flip["dumpRevenue"] == 800
    assert flip["dumpProfit"] == 700
    assert flip["dumpBasis"] == "median of recent sales"
    assert flip["dumpSales"] == 3
    assert flip["dumpLastAt"] == "2026-10-01T00:00:00Z"


def test_instasell_is_none_when_the_item_has_no_fixed_sell_price():
    """Absent from the table means unknown, never guessed."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)], output_count=2),
        market,
        sales=StubSales({"out": 400}),
        sell_prices=StubSellPrices({}),
    )
    assert flip["instasellUnitPrice"] is None
    assert flip["instasellRevenue"] is None
    assert flip["instasellProfit"] is None
    assert flip["instasellMargin"] is None
    assert flip["instasellBasis"] is None
    # the market dump still prices the row
    assert flip["dumpProfit"] == 700


def test_instasell_is_none_without_a_price_table_at_all():
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(recipe([item("a", 1)]), market)
    assert flip["instasellProfit"] is None
    assert flip["profit"] == 400  # the listing side is unaffected


def test_instasell_can_lose_money_while_listing_profits():
    """The point of the column: a craft the server pays less for than it cost."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]), market, sell_prices=StubSellPrices({"out": 50})
    )
    assert flip["profit"] == 400
    assert flip["instasellProfit"] == -50
    assert flip["instasellMargin"] < 0


def test_instasell_takes_the_same_fee():
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        fee_percent=10.0,
        sell_prices=StubSellPrices({"out": 400}),
    )
    assert flip["instasellFee"] == 40
    assert flip["instasellProfit"] == 260  # 400 - 100 - 40


def test_instasell_sort_key_sinks_rows_without_a_fixed_price():
    rows = [
        {"instasellProfit": None, "item": "unknown"},
        {"instasellProfit": 5.0, "item": "small"},
        {"instasellProfit": 900.0, "item": "big"},
    ]
    ranked = sorted(rows, key=SORTS["instasellProfit"], reverse=True)
    assert [r["item"] for r in ranked] == ["big", "small", "unknown"]


# ------------------------------------------------------------- confidence ----

def test_confidence_is_high_for_a_listed_item_with_a_real_sell_price():
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        sales=StubSales({"out": 400}),
        sell_prices=StubSellPrices({"out": 400}),
        index_age=0.0,
        index_ttl=600.0,
    )
    assert flip["confidence"] >= 75
    assert flip["confidenceLabel"] == "high"
    # every material buyable and a real /sell price -> those factors max out
    factors = {f["key"]: f for f in flip["confidenceFactors"]}
    assert factors["costBasis"]["score"] == 1.0
    assert factors["sellBasis"]["score"] == 1.0
    assert factors["freshness"]["score"] == 1.0


def test_confidence_is_low_without_a_sell_side_or_recorded_sales():
    market = StubMarket({"a": entry(market_value=100), "out": entry(market_value=500)})
    flip = compute_flip(recipe([item("a", 1)]), market)
    assert flip["confidence"] < 40
    assert flip["confidenceLabel"] in {"low", "very low"}
    factors = {f["key"]: f for f in flip["confidenceFactors"]}
    assert factors["sellBasis"]["score"] == 0.0
    assert factors["salesDepth"]["score"] == 0.0
    assert factors["costBasis"]["score"] == 0.0  # nothing was buyable


def test_confidence_falls_when_the_prices_disagree():
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    agreed = compute_flip(
        recipe([item("a", 1)]),
        market,
        sales=StubSales({"out": 500}),
        sell_prices=StubSellPrices({"out": 500}),
    )
    disagreed = compute_flip(
        recipe([item("a", 1)]),
        market,
        sales=StubSales({"out": 50_000}),
        sell_prices=StubSellPrices({"out": 50_000}),
    )
    assert disagreed["confidence"] < agreed["confidence"]


def test_confidence_rises_with_more_recorded_sales():
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})

    def with_sales(n):
        sales = StubSales({"out": 400})
        sales.entry = lambda name, n=n: {
            "low": 400.0,
            "median": 400.0,
            "high": 400.0,
            "sales": n,
            "lastAt": "2026-10-01T00:00:00Z",
        } if name == "out" else None
        return compute_flip(recipe([item("a", 1)]), market, sales=sales)

    assert with_sales(10)["confidence"] > with_sales(1)["confidence"]


def test_confidence_is_capped_when_materials_cannot_be_bought():
    """A cost built from market values is a guess, so the row cannot read as high."""
    market = StubMarket({"a": entry(market_value=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        sales=StubSales({"out": 400}),
        sell_prices=StubSellPrices({"out": 400}),
        index_age=0.0,
        index_ttl=600.0,
    )
    assert flip["estimated"] is True
    assert flip["confidence"] <= 60
    assert flip["confidenceLabel"] != "high"
    assert any(f["key"] == "unbuyable" for f in flip["confidenceFactors"])


def test_confidence_factors_are_weighted_and_explained():
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        sales=StubSales({"out": 400}),
        sell_prices=StubSellPrices({"out": 400}),
    )
    factors = flip["confidenceFactors"]
    assert {f["key"] for f in factors} == {
        "costBasis",
        "sellBasis",
        "salesDepth",
        "agreement",
        "freshness",
    }
    assert round(sum(f["weight"] for f in factors), 6) == 1.0
    assert all(f["detail"] for f in factors), "every factor must say what it saw"
    assert 0 <= flip["confidence"] <= 100


def test_confidence_is_docked_for_a_tag_resolved_material():
    """A tag material is the cheapest of several candidates, which is optimistic."""
    market = StubMarket(
        {
            "a": entry(listing=100),
            "b": entry(listing=100),
            "out": entry(market_value=500),
        }
    )
    plain = compute_flip(recipe([item("a", 1)]), market)
    tagged = compute_flip(
        recipe([{"tag": "planks", "options": ["a", "b"], "count": 1, "grid": [[0, 0]]}]),
        market,
    )
    assert tagged["confidence"] < plain["confidence"]
    factors = {f["key"]: f for f in tagged["confidenceFactors"]}
    assert "resolved from a tag" in factors["costBasis"]["detail"]


# ------------------------------------------------------- the sell price table ----

def test_sell_price_table_merges_the_volume_copy_over_the_seed():
    import json
    import tempfile

    from app.sellprices import SellPrices

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed.json")
        table = os.path.join(tmp, "table.json")
        with open(seed, "w", encoding="utf-8") as fh:
            json.dump({"multiplier": 1.0, "items": {"oak_log": 300, "sand": 100}}, fh)
        with open(table, "w", encoding="utf-8") as fh:
            json.dump({"multiplier": 2.0, "items": {"oak_log": 999}}, fh)

        prices = SellPrices(path=table, seed_path=seed, multiplier=1.0)
        # the operator's copy wins, the seed still fills the gaps
        assert prices.lookup("oak_log")["base"] == 999
        assert prices.lookup("sand")["base"] == 100
        # and its multiplier applies to items that do not override it
        assert prices.lookup("sand")["payout"] == 200
        assert prices.size() == 2


def test_sell_price_table_reads_a_bare_number_and_rejects_junk():
    import json
    import tempfile

    from app.sellprices import SellPrices

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed.json")
        with open(seed, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "items": {
                        "oak_log": 300,
                        "Diamond": {"base": 1200, "source": "wiki"},
                        "broken": {"source": "wiki"},
                        "negative": -5,
                    }
                },
                fh,
            )
        prices = SellPrices(path=None, seed_path=seed, multiplier=1.0)
        assert prices.lookup("oak_log")["base"] == 300
        assert prices.lookup("diamond")["base"] == 1200  # normalised to snake case
        assert prices.lookup("broken") is None
        assert prices.lookup("negative") is None
        assert prices.size() == 2
        assert len(prices.snapshot()["errors"]) == 2


def test_sell_price_table_applies_a_per_item_multiplier():
    import json
    import tempfile

    from app.sellprices import SellPrices

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed.json")
        with open(seed, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "multiplier": 1.5,
                    "items": {"oak_log": 100, "sand": {"base": 100, "mult": 3.0}},
                },
                fh,
            )
        prices = SellPrices(path=None, seed_path=seed, multiplier=1.0)
        assert prices.payout("oak_log") == 150
        assert prices.payout("sand") == 300


# ------------------------------------------------------------- the order side ----

class StubOrders:
    """Stand-in for OrderBook: item -> a recorded player buy order."""

    def __init__(self, orders: dict[str, dict], ttl_hours: float = 24.0):
        self.revision = 1
        self._ttl = ttl_hours * 3600.0
        self._orders = {}
        for name, raw in orders.items():
            age = raw.pop("ageSeconds", 0.0)
            self._orders[name] = {
                "item": name,
                "unitPrice": raw.get("unitPrice"),
                "quantity": raw.get("quantity", 1),
                "buyer": raw.get("buyer"),
                "note": raw.get("note"),
                "seenAt": "2026-10-03T00:00:00Z",
                "ageSeconds": age,
                "ttlSeconds": self._ttl,
                "stale": age > self._ttl,
            }

    def lookup(self, name):
        return self._orders.get(name)


def test_order_profit_is_the_order_price_minus_the_materials():
    """A player offering more than the materials cost is the whole point of the book."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        orders=StubOrders({"out": {"unitPrice": 900, "quantity": 64, "buyer": "someone"}}),
    )
    assert flip["orderUnitPrice"] == 900
    assert flip["orderRevenue"] == 900
    assert flip["orderProfit"] == 800
    assert flip["orderBuyer"] == "someone"
    assert flip["easyMoney"] is True


def test_order_profit_scales_with_the_recipe_output_count():
    """Four items per craft against an order priced per item is four times the revenue."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)], output_count=4),
        market,
        orders=StubOrders({"out": {"unitPrice": 100, "quantity": 64}}),
    )
    assert flip["orderRevenue"] == 400
    assert flip["orderProfit"] == 300
    # 64 wanted, 4 per craft
    assert flip["orderFillable"] == 16
    assert flip["orderTotalProfit"] == 4800


def test_order_is_none_when_nothing_is_recorded():
    """No order is unknown, not zero -- the row must not claim a buyer exists."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(recipe([item("a", 1)]), market)
    assert flip["orderUnitPrice"] is None
    assert flip["orderProfit"] is None
    assert flip["orderFillable"] is None
    assert flip["easyMoney"] is False


def test_order_losing_money_is_not_easy_money():
    """An order below the materials cost is a real loss, and must not be flagged."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        orders=StubOrders({"out": {"unitPrice": 50, "quantity": 8}}),
    )
    assert flip["orderProfit"] == -50
    assert flip["easyMoney"] is False


def test_a_stale_order_is_never_easy_money():
    """A buyer can fill or withdraw an offer at any moment, so an old one is not a buyer."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        orders=StubOrders({"out": {"unitPrice": 900, "quantity": 8, "ageSeconds": 40 * 3600}}),
    )
    assert flip["orderStale"] is True
    # the arithmetic still stands -- it is the flag that changes
    assert flip["orderProfit"] == 800
    assert flip["easyMoney"] is False


def test_easy_money_needs_a_material_you_can_actually_buy():
    """An order that beats a costed estimate is not money if the inputs are not on sale."""
    # 'a' has a market value but nobody is selling it, so the cost is an estimate
    market = StubMarket({"a": entry(market_value=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        orders=StubOrders({"out": {"unitPrice": 900, "quantity": 8}}),
    )
    assert flip["estimated"] is True
    assert flip["actionable"] is False
    assert flip["orderProfit"] is not None
    assert flip["easyMoney"] is False


def test_easy_money_needs_an_order_that_absorbs_a_whole_craft():
    """An order wanting fewer items than one craft makes cannot be filled by crafting."""
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)], output_count=4),
        market,
        orders=StubOrders({"out": {"unitPrice": 100, "quantity": 2}}),
    )
    assert flip["orderFillable"] == 0
    assert flip["easyMoney"] is False


def test_order_takes_the_same_fee_as_every_other_exit():
    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    flip = compute_flip(
        recipe([item("a", 1)]),
        market,
        fee_percent=10.0,
        orders=StubOrders({"out": {"unitPrice": 1000, "quantity": 4}}),
    )
    assert flip["orderFee"] == 100
    assert flip["orderProfit"] == 800


def test_order_sort_key_sinks_rows_without_one():
    """Sorting by an order must not let a row with no order outrank a real one."""
    assert SORTS["orderProfit"]({"orderProfit": None}) == float("-inf")
    assert SORTS["orderTotalProfit"]({"orderTotalProfit": None}) == float("-inf")
    assert SORTS["orderProfit"]({"orderProfit": -5}) == -5


def test_a_live_order_raises_confidence_over_a_bare_sell_price():
    """A named buyer at a known price is better evidence than the server's base."""
    from app.confidence import score

    market = StubMarket({"a": entry(listing=100), "out": entry(market_value=500)})
    base = compute_flip(
        recipe([item("a", 1)]),
        market,
        sales=StubSales({"out": 400}),
        sell_prices=StubSellPrices({"out": 300}),
    )
    with_order = compute_flip(
        recipe([item("a", 1)]),
        market,
        sales=StubSales({"out": 400}),
        sell_prices=StubSellPrices({"out": 300}),
        orders=StubOrders({"out": {"unitPrice": 400, "quantity": 64}}),
    )
    bare = score(base, base.get("sellPrice"), index_age=5, index_ttl=600)
    scored = score(with_order, with_order.get("sellPrice"), index_age=5, index_ttl=600)
    assert scored["confidence"] > bare["confidence"]
    basis = [f for f in scored["confidenceFactors"] if f["key"] == "sellBasis"][0]
    assert "live order" in basis["detail"]


# --------------------------------------------------- the order book itself ----

def test_order_book_merges_the_volume_copy_over_the_seed():
    """An order recorded at runtime must survive a redeploy of the image."""
    import json
    import tempfile

    from app.orders import OrderBook

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed.json")
        live = os.path.join(tmp, "orders.json")
        with open(seed, "w", encoding="utf-8") as fh:
            json.dump({"orders": {"a": {"price": 10, "quantity": 1}}}, fh)
        with open(live, "w", encoding="utf-8") as fh:
            json.dump({"orders": {"a": {"price": 99, "quantity": 4}}}, fh)
        book = OrderBook(path=live, seed_path=seed)
        assert book.size() == 1
        assert book.lookup("a")["unitPrice"] == 99
        assert book.lookup("a")["quantity"] == 4


def test_order_book_reads_a_list_and_a_bare_number():
    import json
    import tempfile

    from app.orders import OrderBook

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed.json")
        with open(seed, "w", encoding="utf-8") as fh:
            json.dump({"orders": [{"item": "a", "price": 5, "quantity": 2}, {"item": "b", "price": 7}]}, fh)
        book = OrderBook(path=None, seed_path=seed)
        assert book.lookup("a")["quantity"] == 2
        assert book.lookup("b")["unitPrice"] == 7


def test_order_book_derives_a_unit_price_from_a_total():
    """In game the order can be quoted as a total; the book stores per item."""
    import json
    import tempfile

    from app.orders import OrderBook

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed.json")
        with open(seed, "w", encoding="utf-8") as fh:
            json.dump({"orders": [{"item": "a", "totalPrice": 640, "quantity": 64}]}, fh)
        book = OrderBook(path=None, seed_path=seed)
        assert book.lookup("a")["unitPrice"] == 10


def test_order_book_rejects_junk_instead_of_guessing():
    import json
    import tempfile

    from app.orders import OrderBook

    with tempfile.TemporaryDirectory() as tmp:
        seed = os.path.join(tmp, "seed.json")
        with open(seed, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "orders": [
                        {"item": "noprice"},
                        {"item": "zero", "price": 0},
                        {"item": "negative", "price": -5},
                        {"item": "badqty", "price": 10, "quantity": 0},
                        {"price": 10},
                    ]
                },
                fh,
            )
        book = OrderBook(path=None, seed_path=seed)
        assert book.size() == 0
        assert len(book.snapshot()["errors"]) == 5


def test_order_book_write_then_read_round_trips():
    """The write path is what the API uses, so it has to land where the read looks."""
    import tempfile

    from app.orders import OrderBook

    with tempfile.TemporaryDirectory() as tmp:
        live = os.path.join(tmp, "orders.json")
        book = OrderBook(path=live, seed_path=None)
        assert book.size() == 0
        saved = book.put("netherite_ingot", 5_000_000, quantity=64, buyer="someone")
        assert saved["unitPrice"] == 5_000_000
        assert saved["quantity"] == 64
        assert book.size() == 1
        # a second book over the same file sees it, which is what a redeploy does
        assert OrderBook(path=live, seed_path=None).lookup("netherite_ingot")["buyer"] == "someone"
        assert book.drop("netherite_ingot") is True
        assert book.size() == 0
        assert book.drop("netherite_ingot") is False


def test_order_book_normalises_the_item_name():
    import tempfile

    from app.orders import OrderBook

    with tempfile.TemporaryDirectory() as tmp:
        book = OrderBook(path=os.path.join(tmp, "orders.json"), seed_path=None)
        book.put("Netherite Ingot", 10, quantity=1)
        assert book.lookup("netherite_ingot") is not None
        assert book.lookup("minecraft:netherite_ingot") is not None


def test_order_book_write_rejects_a_bad_price():
    import tempfile

    from app.orders import OrderBook

    with tempfile.TemporaryDirectory() as tmp:
        book = OrderBook(path=os.path.join(tmp, "orders.json"), seed_path=None)
        for bad in (0, -1):
            try:
                book.put("a", bad, quantity=1)
            except ValueError:
                continue
            raise AssertionError(f"price {bad} should have been rejected")
        assert book.size() == 0


def test_an_empty_order_book_stops_bumping_its_revision():
    """An empty book is a stable state.

    Guarding reload() on the book being non-empty made it re-read and bump `revision`
    on every call, which made FlipTable._is_fresh always false and rebuilt the whole
    table on every request. Regression test for that.
    """
    import tempfile

    from app.orders import OrderBook

    with tempfile.TemporaryDirectory() as tmp:
        book = OrderBook(path=os.path.join(tmp, "orders.json"), seed_path=None)
        assert book.size() == 0
        first = book.revision
        for _ in range(25):
            book.refresh()
        assert book.revision == first, "an empty book re-read and bumped revision"
        # and a real write still bumps it, so the table notices
        book.put("a", 10, quantity=1)
        assert book.revision > first
        after = book.revision
        for _ in range(10):
            book.refresh()
        assert book.revision == after


def test_an_empty_sell_price_table_stops_bumping_its_revision():
    """Same guard, same bug, in the /sell table."""
    import tempfile

    from app.sellprices import SellPrices

    with tempfile.TemporaryDirectory() as tmp:
        table = SellPrices(path=os.path.join(tmp, "sell.json"), seed_path=None)
        assert table.size() == 0
        first = table.revision
        for _ in range(25):
            table.refresh()
        assert table.revision == first, "an empty table re-read and bumped revision"


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
