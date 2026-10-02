"""Run one full index refresh against live upstream and print the resulting table.

The real pre-deploy check: it exercises the market index, the flip engine and the
dataset together, with no HTTP server in the way.

  python tools/local_check.py [max_requests]

`max_requests` caps upstream calls so the run can be kept short while iterating.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402
from app.donut import DonutClient  # noqa: E402
from app.flips import FlipTable, load_recipes  # noqa: E402
from app.market import MAX_REQUESTS_PER_REFRESH, Market  # noqa: E402


async def main() -> int:
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_REQUESTS_PER_REFRESH

    doc = load_recipes(config.RECIPES_PATH)
    print(f"recipes: {doc['counts']}")
    print(f"mc {doc['mcVersion']}  sha256 {doc['sha256'][:16]}…")

    client = DonutClient(base=config.UPSTREAM_BASE, ttl=15.0)
    await client.startup()
    try:
        market = Market(client, doc["recipes"], ttl=600, spacing=config.REQUEST_SPACING_SECONDS)
        print(
            f"\ningredients to price: {len(market.ingredient_names)}  "
            f"potential outputs: {len(market.output_names)}  cap {cap} requests"
        )
        globals()["MAX_REQUESTS_PER_REFRESH"] = cap

        import app.market as m

        original = m.MAX_REQUESTS_PER_REFRESH
        m.MAX_REQUESTS_PER_REFRESH = cap
        t0 = time.time()
        try:
            snap = await market.refresh()
        finally:
            m.MAX_REQUESTS_PER_REFRESH = original
        print(f"refresh took {time.time() - t0:.1f}s")
        print(
            f"index {snap['indexSize']} priced  ({snap['missingCount']} missing of "
            f"{snap['needed']})  outputsQueried={snap['outputsQueried']}  "
            f"requests={snap['requestsUsed']}  upstreamOk={snap['upstreamOk']}"
        )
        if snap["lastError"]:
            print(f"  lastError: {snap['lastError']}")

        table = FlipTable(market, doc["recipes"], config.DONUT_FEE_PERCENT, 30.0)
        rows = await table.rows()
        print(f"\nflips found: {len(rows)} of {len(doc['recipes'])} recipes")
        print(f"{'item':<26}{'cost':>13}{'sells for':>13}{'profit':>13}{'margin':>9}  est")
        for r in rows[:20]:
            print(
                f"{r['item']:<26}{r['cost']:>13,.0f}{r['revenue']:>13,.0f}"
                f"{r['profit']:>13,.0f}{r['margin'] * 100:>8.1f}%  {'yes' if r['estimated'] else ''}"
            )

        # the plan's hand-check: netherite ingot is 4 scrap + 4 gold
        n = await table.find("netherite_ingot")
        if n:
            print("\nhand-check netherite_ingot:")
            for ing in n["ingredients"]:
                print(f"  {ing['count']}× {ing['item']:<20} @ {ing['unitPrice']:>12,.0f} = {ing['subtotal']:>13,.0f} ({ing['source']})")
            print(f"  cost {n['cost']:,.0f}  sells for {n['revenue']:,.0f}  profit {n['profit']:,.0f}")
        else:
            print("\nnetherite_ingot: not costable in this run (an ingredient had no price)")
        return 0
    finally:
        await client.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
