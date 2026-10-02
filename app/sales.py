"""The sell side: what an item has actually sold for recently.

DonutSMP has no public bid side. donut.auction retired its order data -- its
/orders page says "Order data has been retired", /v1/orders/items/{id}/prices is
404 and /v2/orders/search/ now returns an empty list -- and the official
api.donutsmp.net exposes auction listings and transactions only. So the price an
item can actually be dumped at has to come from what it has really sold for.

That costs one upstream request per item, far too much to fold into the price
refresh, so this index fills on its own slower cycle: an item simply has no dump
price until its turn comes round, and the ledger shows a dash until then.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Iterable

from .donut import UpstreamError, sale_row, summarise_sales

log = logging.getLogger("craftflip.sales")

# The dump price is the middle of the recent range, not its floor: a single
# outlier dump (waxed_weathered_chiseled_copper has one at 6,250 against a 2.4M
# index) would otherwise produce a nonsense number for the whole item.
BASIS = "median of recent sales"


class SalesIndex:
    """Per-item sales summaries, refreshed lazily on a slow cycle."""

    def __init__(self, ttl: float = 1800.0, spacing: float = 1.0, max_per_cycle: int = 300) -> None:
        self.ttl = ttl
        self.spacing = spacing
        self.max_per_cycle = max_per_cycle
        self.basis = BASIS
        self._entries: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task | None = None
        self._client: Any = None
        self._market: Any = None
        self.requests = 0
        self.last_error: str | None = None
        self.last_pass: float | None = None
        # bumped on every stored entry so the flip table can tell that new sell-side
        # data has landed without waiting for a whole pass to finish
        self.revision = 0

    async def start(self, client: Any, market: Any) -> None:
        self._client = client
        self._market = market
        self._task = asyncio.create_task(self._loop(), name="sales-refresh")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ---------------------------------------------------------------- reads ----
    def _fresh(self, name: str) -> bool:
        entry = self._entries.get(name)
        return bool(entry) and (time.monotonic() - entry["monotonic"]) < self.ttl

    def entry(self, name: str) -> dict[str, Any] | None:
        """The recent-sales summary for an item, or None when it is not known yet."""
        return self._entries.get(name) if self._fresh(name) else None

    def price(self, name: str) -> float | None:
        entry = self.entry(name)
        return (entry or {}).get("median") or None

    def size(self) -> int:
        return sum(1 for name in self._entries if self._fresh(name))

    def snapshot(self) -> dict[str, Any]:
        return {
            "priced": self.size(),
            "tracked": len(self._entries),
            "ttlSeconds": self.ttl,
            "basis": self.basis,
            "requests": self.requests,
            "lastError": self.last_error,
            "lastPassAt": (
                None
                if self.last_pass is None
                else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_pass))
            ),
        }

    # --------------------------------------------------------------- refresh ----
    async def refresh(self, client: Any, market: Any, names: Iterable[str] | None = None) -> int:
        """One pass: refresh every stale item, at most max_per_cycle requests."""
        if names is None:
            names = market.costable_outputs(market.index)
        todo = [n for n in names if not self._fresh(n)]
        done = 0
        for name in todo:
            if done >= self.max_per_cycle:
                break
            entry = market.lookup(name)
            if not entry or not entry.get("itemId"):
                continue
            try:
                tx = await client.transactions(entry["itemId"])
            except UpstreamError as exc:
                self.last_error = str(exc)
                continue
            summary = summarise_sales([sale_row(t) for t in tx])
            summary["monotonic"] = time.monotonic()
            summary["fetchedAt"] = time.time()
            self._entries[name] = summary
            self.requests += 1
            self.revision += 1
            done += 1
            await asyncio.sleep(self.spacing)
        self.last_pass = time.time()
        return done

    async def _loop(self) -> None:
        # no price index means no item ids, so there is nothing to look up yet
        while getattr(self._market, "built_at", None) is None:
            await asyncio.sleep(5)
        while True:
            try:
                did = await self.refresh(self._client, self._market)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                log.warning("sales refresh: %s", exc)
                did = 0
            # nothing left to fetch -- rest until the oldest entry goes stale
            if did == 0:
                await asyncio.sleep(max(30.0, self.ttl / 4))
