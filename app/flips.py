"""The craft-flip engine.

For every vanilla crafting recipe: cost the materials, value the output, and rank
the difference. Nothing here talks to the network except the optional recent-sales
lookup on a single item's detail page -- the table is pure arithmetic over the
market index, so polling it costs upstream nothing.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Iterable

from . import confidence
from .donut import prettify
from .market import Market, ingredient_options


class RecipeDataError(RuntimeError):
    pass


def load_recipes(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise RecipeDataError(
            f"recipe dataset missing at {p}. Generate it with tools/build_recipes.py "
            f"(see README) -- craftflip will not guess a recipe set."
        )
    with p.open(encoding="utf-8") as fh:
        doc = json.load(fh)
    if not doc.get("recipes"):
        raise RecipeDataError(f"recipe dataset at {p} contains no recipes")
    return doc


def needed_names(recipes: Iterable[dict[str, Any]]) -> set[str]:
    """Every item name the engine could possibly price."""
    out: set[str] = set()
    for r in recipes:
        out.add(r["output"]["item"])
        for ing in r["ingredients"]:
            out.update(ingredient_options(ing))
    return out


def cost_ingredient(ing: dict[str, Any], market: Market) -> dict[str, Any] | None:
    """Cheapest way to satisfy one ingredient slot, or None if nothing is priced.

    A tag or an explicit list resolves to whichever member is cheapest to buy.
    """
    options = ingredient_options(ing)
    best: dict[str, Any] | None = None
    for name in options:
        entry = market.lookup(name)
        if not entry:
            continue
        live = entry.get("cheapestListing") or {}
        unit = live.get("unitPrice")
        source = "listing"
        if unit is None:
            unit = entry.get("marketValue")
            source = "market"
        if unit is None or unit <= 0:
            continue
        if best is None or unit < best["unitPrice"]:
            best = {
                "item": name,
                "displayName": entry.get("displayName") or prettify(name),
                "unitPrice": float(unit),
                "source": source,
                "via": ing.get("tag") or ("choice" if len(options) > 1 else "item"),
                "optionsConsidered": len(options),
            }
    if best is None:
        return None
    best["count"] = ing["count"]
    best["subtotal"] = round(best["unitPrice"] * ing["count"], 4)
    return best


def value_output(
    output: dict[str, Any], market: Market, sales: Any = None
) -> dict[str, Any] | None:
    """What the crafted output sells for, per the market -- and what it would fetch
    if it had to be dumped now, per what it has actually sold for recently."""
    name = output["item"]
    entry = market.lookup(name)
    if not entry:
        return None
    live = entry.get("cheapestListing") or {}
    market_value = entry.get("marketValue")
    listing = live.get("unitPrice")
    if market_value and market_value > 0:
        unit, source = float(market_value), "market"
    elif listing and listing > 0:
        unit, source = float(listing), "listing"
    else:
        return None
    count = int(output.get("count") or 1)
    sold = sales.entry(name) if sales is not None else None
    dump = (sold or {}).get("median")
    return {
        "item": name,
        "displayName": entry.get("displayName") or prettify(name),
        "count": count,
        "unitPrice": unit,
        "source": source,
        "total": round(unit * count, 4),
        "cheapestListing": listing,
        "cheapestListingAt": live.get("observedAt"),
        "volume24h": entry.get("volume24h") or 0.0,
        "sales24h": entry.get("sales24h") or 0.0,
        "itemId": entry.get("itemId"),
        # the sell side, from completed sales rather than the price index
        "dumpUnitPrice": float(dump) if dump else None,
        "dumpSales": (sold or {}).get("sales"),
        "dumpLow": (sold or {}).get("low"),
        "dumpMedian": (sold or {}).get("median"),
        "dumpHigh": (sold or {}).get("high"),
        "dumpLastAt": (sold or {}).get("lastAt"),
    }


def compute_flip(
    recipe: dict[str, Any],
    market: Market,
    fee_percent: float = 0.0,
    sales: Any = None,
    sell_prices: Any = None,
    index_age: float | None = None,
    index_ttl: float = 600.0,
) -> dict[str, Any] | None:
    """Cost, value and rank one recipe. None when it cannot be priced."""
    costs: list[dict[str, Any]] = []
    for ing in recipe["ingredients"]:
        got = cost_ingredient(ing, market)
        if got is None:
            return None  # a leg with no price at all -- skip the whole recipe
        costs.append(got)

    cost = round(sum(c["subtotal"] for c in costs), 4)
    if cost <= 0:
        return None  # free materials make margin meaningless

    out = value_output(recipe["output"], market, sales)
    if out is None:
        return None

    revenue = out["total"]
    fee = round(revenue * fee_percent / 100.0, 4)
    profit = round(revenue - cost - fee, 4)
    margin = profit / cost
    listed = [c for c in costs if c["source"] == "listing"]

    # The fixed /sell payout: the server's base price times your own multiplier for
    # that item. It is the one exit that needs no other player, and because the
    # server does not publish the base prices, an item with no entry in the table
    # gets None rather than a guess. /sell also routes to a matching order when one
    # pays more, but order data is retired upstream, so there is nothing to compare.
    sell = sell_prices.lookup(recipe["output"]["item"]) if sell_prices is not None else None
    sell_unit = sell["payout"] if sell else None
    sell_revenue = round(sell_unit * out["count"], 4) if sell_unit else None
    sell_fee = round(sell_revenue * fee_percent / 100.0, 4) if sell_revenue else None
    sell_profit = (
        round(sell_revenue - cost - (sell_fee or 0.0), 4) if sell_revenue is not None else None
    )

    # What the item has actually cleared at recently: the market's exit, not the
    # server's. None until the sales index has looked this item up.
    dump_unit = out["dumpUnitPrice"]
    dump_revenue = round(dump_unit * out["count"], 4) if dump_unit else None
    dump_fee = round(dump_revenue * fee_percent / 100.0, 4) if dump_revenue else None
    dump_profit = (
        round(dump_revenue - cost - (dump_fee or 0.0), 4) if dump_revenue is not None else None
    )

    flip: dict[str, Any] = {
        "item": recipe["output"]["item"],
        "displayName": out["displayName"],
        "recipeId": recipe["id"],
        "recipeType": recipe["type"],
        "cost": cost,
        "revenue": revenue,
        "fee": fee,
        "profit": profit,
        "margin": margin,
        "outputCount": out["count"],
        "costPerUnit": round(cost / out["count"], 4),
        "profitPerUnit": round(profit / out["count"], 4),
        # the fixed server exit
        "instasellUnitPrice": sell_unit,
        "instasellRevenue": sell_revenue,
        "instasellFee": sell_fee,
        "instasellProfit": sell_profit,
        "instasellMargin": (sell_profit / cost) if sell_profit is not None else None,
        "instasellBasis": "server /sell base price" if sell_unit else None,
        "instasellBasePrice": (sell or {}).get("base"),
        "instasellMultiplier": (sell or {}).get("multiplier"),
        "instasellSource": (sell or {}).get("source"),
        "instasellNote": (sell or {}).get("note"),
        # the market exit, from completed sales
        "dumpUnitPrice": dump_unit,
        "dumpRevenue": dump_revenue,
        "dumpProfit": dump_profit,
        "dumpMargin": (dump_profit / cost) if dump_profit is not None else None,
        "dumpBasis": getattr(sales, "basis", None) if dump_unit else None,
        "dumpSales": out["dumpSales"],
        "dumpLastAt": out["dumpLastAt"],
        # true when a material had no live listing and its market value stood in
        "estimated": len(listed) < len(costs),
        # every material is buyable right now, so this flip can actually be executed
        "actionable": len(listed) == len(costs),
        "materialsTotal": len(costs),
        "materialsListed": len(listed),
        "alternates": 0,
        "ingredients": costs,
        "output": out,
        "listedNow": out["cheapestListing"],
        # when the live listing behind "listed now" was observed upstream
        "listedAt": out["cheapestListingAt"],
    }
    flip.update(confidence.score(flip, sell, index_age, index_ttl))
    return flip


SORTS = {
    "profit": lambda f: f["profit"],
    "margin": lambda f: f["margin"],
    "cost": lambda f: f["cost"],
    "revenue": lambda f: f["revenue"],
    "item": lambda f: f["item"],
    "profitPerUnit": lambda f: f["profitPerUnit"],
    "confidence": lambda f: f["confidence"],
    # rows with no fixed sell price sort last rather than being treated as zero
    "instasellProfit": lambda f: (
        f["instasellProfit"] if f["instasellProfit"] is not None else float("-inf")
    ),
    # same for rows with no recorded sales to price a dump from
    "dumpProfit": lambda f: (
        f["dumpProfit"] if f["dumpProfit"] is not None else float("-inf")
    ),
}


class FlipTable:
    """Recomputes the ranked table from the market index, cached briefly."""

    def __init__(
        self,
        market: Market,
        recipes: list[dict[str, Any]],
        fee_percent: float = 0.0,
        ttl: float = 30.0,
        sales: Any = None,
        sell_prices: Any = None,
    ):
        self.market = market
        self.recipes = recipes
        self.fee_percent = fee_percent
        self.ttl = ttl
        self.sales = sales
        self.sell_prices = sell_prices
        self._rows: list[dict[str, Any]] | None = None
        self._built_at: float | None = None
        self._index_built_at: float | None = None
        self._sales_revision: int | None = None
        self._sell_revision: int | None = None
        self._lock = asyncio.Lock()

    def _is_fresh(self) -> bool:
        if self._rows is None or self._built_at is None:
            return False
        if time.time() - self._built_at > self.ttl:
            return False
        # recompute if the underlying index was refreshed underneath us
        if self._index_built_at != self.market.built_at:
            return False
        # the sales index fills in slowly in the background, so a new sell-side
        # price should surface without waiting for the next price refresh. Compare a
        # revision counter, not the last-pass timestamp: that stays None until a
        # whole pass finishes, which would keep an empty table looking fresh.
        if self._sales_revision != getattr(self.sales, "revision", 0):
            return False
        # same for the /sell price table: an edit to it should show up immediately
        return self._sell_revision == getattr(self.sell_prices, "revision", 0)

    async def rows(self) -> list[dict[str, Any]]:
        if self._is_fresh():
            return self._rows or []
        async with self._lock:
            if self._is_fresh():
                return self._rows or []
            age = self.market.age
            ttl = self.market.ttl
            built = self._dedupe(
                compute_flip(
                    r,
                    self.market,
                    self.fee_percent,
                    self.sales,
                    self.sell_prices,
                    age,
                    ttl,
                )
                for r in self.recipes
            )
            built.sort(key=lambda f: f["profit"], reverse=True)
            self._rows = built
            self._built_at = time.time()
            self._index_built_at = self.market.built_at
            self._sales_revision = getattr(self.sales, "revision", 0)
            self._sell_revision = getattr(self.sell_prices, "revision", 0)
            return built

    @staticmethod
    def _dedupe(flips: Iterable[dict[str, Any] | None]) -> list[dict[str, Any]]:
        """One row per output item: the best way to make it.

        Several recipes produce the same item (a direct craft and a 'from_block'
        variant, say). Listing both would show the same item twice with different
        costs, which reads as a bug. Keep one, preferring a recipe whose materials
        are all buyable right now, then the higher profit, and count the rest.
        """
        best: dict[str, dict[str, Any]] = {}
        for flip in flips:
            if flip is None:
                continue
            item = flip["item"]
            prev = best.get(item)
            if prev is None:
                best[item] = flip
                continue
            prev["alternates"] += 1
            if (flip["actionable"], flip["profit"]) > (prev["actionable"], prev["profit"]):
                flip["alternates"] = prev["alternates"]
                best[item] = flip
        return list(best.values())

    def stats(self) -> dict[str, Any]:
        return {
            "recipesConsidered": len(self.recipes),
            "flipsFound": len(self._rows or []),
            "computedAt": (
                None
                if self._built_at is None
                else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._built_at))
            ),
            "feePercent": self.fee_percent,
        }

    async def query(
        self,
        q: str | None = None,
        min_profit: float | None = None,
        min_margin: float | None = None,
        min_confidence: int | None = None,
        sort: str = "profit",
        limit: int = 100,
        profitable_only: bool = True,
    ) -> list[dict[str, Any]]:
        rows = await self.rows()
        out = rows
        if q:
            needle = q.strip().lower().replace(" ", "_")
            out = [r for r in out if needle in r["item"]]
        if min_profit is not None:
            out = [r for r in out if r["profit"] >= min_profit]
        if min_margin is not None:
            out = [r for r in out if r["margin"] >= min_margin]
        if min_confidence is not None:
            out = [r for r in out if r["confidence"] >= min_confidence]
        if profitable_only and min_profit is None:
            out = [r for r in out if r["profit"] > 0]
        key = SORTS.get(sort, SORTS["profit"])
        reverse = sort != "item"
        return sorted(out, key=key, reverse=reverse)[: max(1, min(limit, 500))]

    async def find(self, item_name: str) -> dict[str, Any] | None:
        needle = item_name.strip().lower().replace(" ", "_")
        for r in await self.rows():
            if r["item"] == needle:
                return r
        return None


def recipe_grid(recipe: dict[str, Any], market: Market) -> dict[str, Any]:
    """Render a recipe as priced cells for the detail page.

    Shaped recipes get their real 3x3 arrangement. Shapeless ones have no
    arrangement to show, but their slots still need pricing, so they come back as a
    flat tray of the same cells rather than nothing.
    """
    if recipe["type"] != "crafting_shaped":
        slots = []
        for ing in recipe["ingredients"]:
            priced = cost_ingredient(ing, market)
            slots.append(
                {
                    "item": (priced or {}).get("item") or (ingredient_options(ing) or [None])[0],
                    "displayName": (priced or {}).get("displayName"),
                    "unitPrice": (priced or {}).get("unitPrice"),
                    "tag": ing.get("tag"),
                    "count": ing["count"],
                }
            )
        return {"type": recipe["type"], "size": None, "cells": None, "slots": slots}

    size = 3
    cells: list[list[dict[str, Any] | None]] = [[None] * size for _ in range(size)]
    for ing in recipe["ingredients"]:
        priced = cost_ingredient(ing, market)
        for r, c in ing.get("grid", []):
            if 0 <= r < size and 0 <= c < size:
                cells[r][c] = {
                    "item": (priced or {}).get("item") or (ingredient_options(ing) or [None])[0],
                    "displayName": (priced or {}).get("displayName"),
                    "unitPrice": (priced or {}).get("unitPrice"),
                    "tag": ing.get("tag"),
                }
    return {"type": recipe["type"], "size": size, "cells": cells, "slots": None}
