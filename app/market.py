"""Market index for craftflip.

Builds name -> price for the item names that a vanilla crafting recipe actually
needs. It does not try to index the whole market, because api.donut.auction cannot
be enumerated: /v2/items/search is substring-matched and hard-capped at 25 results
with no pagination (see PROBE.md).

Strategy, in order:
  1. /v2/tickers/ -- one request, live listing prices for the ~45 hottest items.
  2. Ingredients, by greedy token sweep -- because matching is substring, one query
     covers every needed name containing that substring. Most-covering token first.
  3. Ingredients, per-name -- anything the sweep did not see gets its own query.
  4. Outputs, same two stages -- but only for recipes whose every material is now
     priced. A recipe that already cannot be costed never has its output queried.

A query returns at most 25 matches, so a sweep token is never assumed to have
returned everything it matches. Coverage is tracked by returned itemName, and a name
only counts as found when it is actually seen.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Iterable

from .donut import DonutClient, prettify

log = logging.getLogger("craftflip.market")

# Guard rail: never let one refresh spiral into unbounded requests.
MAX_REQUESTS_PER_REFRESH = 1400
# Tokens shorter than this match far too much to be useful.
MIN_TOKEN_LEN = 3


def ingredient_options(ing: dict[str, Any]) -> list[str]:
    """Every concrete item name that could satisfy this ingredient slot."""
    if "item" in ing:
        return [ing["item"]]
    if "options" in ing:
        return list(ing["options"])
    return []


def plain_entry(entries: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Pick the plain, unmodified tradeable entry for `name`.

    One itemName can appear several times with different ids -- those are
    player-customised items with a styled displayName. A renamed cosmetic axe must
    never be mistaken for the real market price, so a plain item (no enchantments,
    no displayName) always wins. Returns None if the name is not present at all.
    """
    exact = [
        e for e in entries
        if (e.get("item", {}).get("itemName") or "").lower() == name
    ]
    if not exact:
        return None
    plain = [
        e for e in exact
        if not e["item"].get("enchantments") and not e["item"].get("displayName")
    ]
    return (plain or exact)[0]


def entry_from_search(entry: dict[str, Any]) -> dict[str, Any]:
    item = entry["item"]
    price = entry.get("price") or {}
    name = (item.get("itemName") or "").lower()
    return {
        "itemId": item.get("id"),
        "itemName": name,
        "displayName": prettify(name),
        "marketValue": _num(price.get("value")),
        "volume24h": _num(price.get("volume24Hours")) or 0.0,
        "sales24h": _num(price.get("saleCount24Hours")) or 0.0,
        "cheapestListing": None,
    }


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def candidate_tokens(needed: Iterable[str]) -> list[str]:
    """Query strings worth spending a request on, most-covering first.

    Only substrings that cover two or more needed names are worth a sweep: a token
    covering one name is no cheaper than that name's own lookup, which the fallback
    stage does anyway.
    """
    coverage: dict[str, set[str]] = {}
    for name in needed:
        parts = name.split("_")
        for tok in {name, *parts, parts[-1]}:
            if len(tok) >= MIN_TOKEN_LEN:
                coverage.setdefault(tok, set()).add(name)
    scored = sorted(coverage.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [tok for tok, names in scored if len(names) >= 2]


class Market:
    """Holds the current price index and refreshes it in the background."""

    def __init__(
        self,
        client: DonutClient,
        recipes: list[dict[str, Any]],
        ttl: float = 600.0,
        spacing: float = 0.25,
        max_requests: int | None = None,
    ):
        self.client = client
        self.recipes = recipes
        self.ttl = ttl
        self.spacing = spacing
        self.max_requests = max_requests or MAX_REQUESTS_PER_REFRESH

        self.ingredient_names: set[str] = {
            n for r in recipes for ing in r["ingredients"] for n in ingredient_options(ing)
        }
        self.output_names: set[str] = {r["output"]["item"] for r in recipes}

        self.index: dict[str, dict[str, Any]] = {}
        self.built_at: float | None = None
        self.build_seconds: float | None = None
        self.upstream_ok = False
        self.last_error: str | None = None
        self.requests_used = 0
        self.outputs_queried = 0

        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stopping = False

    # ---- lifecycle ------------------------------------------------------
    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="market-refresh")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("market refresh failed: %s", exc)
                self.upstream_ok = False
                self.last_error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(self.ttl)

    # ---- freshness ------------------------------------------------------
    @property
    def age(self) -> float | None:
        return None if self.built_at is None else time.time() - self.built_at

    def is_stale(self) -> bool:
        return self.age is None or self.age > self.ttl

    async def ensure_fresh(self) -> None:
        """Kick a refresh if the index is stale. Never blocks on a live refresh."""
        if not self.is_stale() or self._lock.locked():
            return
        asyncio.create_task(self.refresh())

    # ---- the refresh itself ---------------------------------------------
    async def _sweep(self, names: set[str], found: dict[str, Any], errors: list[str]) -> None:
        """Greedy token sweep over `names`, marking what actually comes back."""
        uncovered = set(names) - set(found)
        for tok in candidate_tokens(uncovered):
            if not uncovered or self.requests_used >= self.max_requests:
                break
            try:
                entries = await self.client.search_items(tok)
                self.requests_used += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"search {tok!r}: {type(exc).__name__}: {exc}")
                await asyncio.sleep(self.spacing)
                continue
            for e in entries:
                name = (e["item"].get("itemName") or "").lower()
                if name in uncovered:
                    picked = plain_entry(entries, name)
                    if picked is not None:
                        found[name] = entry_from_search(picked)
                        uncovered.discard(name)
            await asyncio.sleep(self.spacing)

    async def _by_name(self, names: set[str], found: dict[str, Any], errors: list[str]) -> None:
        """One exact query per still-uncovered name."""
        for name in sorted(set(names) - set(found)):
            if self.requests_used >= self.max_requests:
                errors.append("hit MAX_REQUESTS_PER_REFRESH, stopped early")
                break
            try:
                entries = await self.client.search_items(name)
                self.requests_used += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"search {name!r}: {type(exc).__name__}: {exc}")
                await asyncio.sleep(self.spacing)
                continue
            picked = plain_entry(entries, name)
            if picked is not None:
                found[name] = entry_from_search(picked)
            await asyncio.sleep(self.spacing)

    def costable_outputs(self, found: dict[str, Any]) -> set[str]:
        """Outputs of recipes whose every material is now priced.

        A recipe that cannot be costed has no use for its output's price, so this is
        what keeps a 1000-recipe dataset from turning into 1000 output lookups.
        """
        out: set[str] = set()
        for r in self.recipes:
            if all(
                any(n in found for n in ingredient_options(ing))
                for ing in r["ingredients"]
            ):
                out.add(r["output"]["item"])
        return out

    async def refresh(self) -> dict[str, Any]:
        async with self._lock:
            t0 = time.time()
            self.requests_used = 0
            found: dict[str, dict[str, Any]] = {}
            errors: list[str] = []

            # 1. tickers -- free live listings for the hottest items
            try:
                tickers = await self.client.tickers()
                self.requests_used += 1
                listings = self._best_listings_by_name(tickers)
            except Exception as exc:  # noqa: BLE001
                listings = {}
                errors.append(f"tickers: {type(exc).__name__}: {exc}")

            # 2 + 3. ingredients
            await self._sweep(self.ingredient_names, found, errors)
            await self._by_name(self.ingredient_names, found, errors)

            # 4. only the outputs that can actually be costed
            targets = self.costable_outputs(found)
            self.outputs_queried = len(targets)
            await self._sweep(targets, found, errors)
            await self._by_name(targets, found, errors)

            # attach live listings where tickers had one
            for entry in found.values():
                live = listings.get(entry["itemName"])
                if live:
                    entry["cheapestListing"] = live

            # Never empty a good index because of a bad refresh.
            if found:
                self.index = found
                self.built_at = time.time()
                self.build_seconds = round(time.time() - t0, 1)
                self.upstream_ok = not errors
                self.last_error = errors[0] if errors else None
            else:
                self.upstream_ok = False
                self.last_error = errors[0] if errors else "refresh produced no prices"
                log.warning("market refresh produced no prices; keeping previous index")

            return self.snapshot()

    @staticmethod
    def _best_listings_by_name(tickers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for t in tickers:
            name = (t.get("itemName") or "").lower()
            if not name:
                continue
            unit = t.get("unitPrice") or t.get("listingPrice")
            if unit is None:
                continue
            current = out.get(name)
            if current is None or unit < current["unitPrice"]:
                out[name] = {
                    "unitPrice": unit,
                    "listingPrice": t.get("listingPrice"),
                    "quantity": t.get("quantity"),
                    "observedAt": t.get("observedAt"),
                    "isStale": bool(t.get("isStale")),
                }
        return out

    # ---- reads -----------------------------------------------------------
    def lookup(self, name: str) -> dict[str, Any] | None:
        return self.index.get(name)

    @property
    def needed(self) -> set[str]:
        return self.ingredient_names | self.output_names

    def snapshot(self) -> dict[str, Any]:
        missing = sorted(self.needed - set(self.index))
        return {
            "indexSize": len(self.index),
            "needed": len(self.needed),
            "ingredientsNeeded": len(self.ingredient_names),
            "outputsQueried": self.outputs_queried,
            "missingCount": len(missing),
            # a few examples, not the whole list -- this lands in /api/status
            "missingSample": missing[:12],
            "ageSeconds": None if self.age is None else round(self.age, 1),
            "builtAt": (
                None
                if self.built_at is None
                else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.built_at))
            ),
            "buildSeconds": self.build_seconds,
            "requestsUsed": self.requests_used,
            "upstreamOk": self.upstream_ok,
            "lastError": self.last_error,
        }
