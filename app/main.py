"""craftflip HTTP API + SPA host.

Serves the ranked craft-flip ledger and the JSON behind it from one process, so
there is no CORS surface and no second service to deploy.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, config
from .donut import DonutClient, UpstreamError, normalize_query, prettify
from .flips import FlipTable, RecipeDataError, load_recipes, recipe_grid
from .history import FlipHistory
from .market import Market

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("craftflip")

state: dict[str, Any] = {}


async def _history_loop() -> None:
    """Append the top flips once per index refresh."""
    market: Market = state["market"]
    table: FlipTable = state["table"]
    history: FlipHistory = state["history"]
    while True:
        try:
            await asyncio.sleep(config.INDEX_TTL_SECONDS)
            if market.built_at is None:
                continue
            rows = await table.rows()
            history.append(rows, config.DONUT_FEE_PERCENT)
            history.prune()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("history loop: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        doc = load_recipes(config.RECIPES_PATH)
    except RecipeDataError as exc:
        # Start anyway so /health can report exactly what is wrong.
        log.error("recipe dataset unavailable: %s", exc)
        state["recipes_error"] = str(exc)
        doc = {"recipes": [], "mcVersion": None, "generatedAt": None, "sha256": None}

    state["recipes"] = doc["recipes"]
    state["recipes_meta"] = {
        "mcVersion": doc.get("mcVersion"),
        "generatedAt": doc.get("generatedAt"),
        "sha256": doc.get("sha256"),
        "counts": doc.get("counts"),
    }

    client = DonutClient(base=config.UPSTREAM_BASE, ttl=15.0)
    await client.startup()
    market = Market(
        client,
        doc["recipes"],
        ttl=config.INDEX_TTL_SECONDS,
        spacing=config.REQUEST_SPACING_SECONDS,
        max_requests=config.MAX_REQUESTS_PER_REFRESH,
    )
    table = FlipTable(market, doc["recipes"], config.DONUT_FEE_PERCENT, config.FLIPS_TTL_SECONDS)
    history = FlipHistory(config.DATA_DIR, config.HISTORY_TOP_N, config.HISTORY_RETENTION_DAYS)

    state.update({"client": client, "market": market, "table": table, "history": history})
    await market.start()
    hist_task = asyncio.create_task(_history_loop(), name="flip-history")

    try:
        yield
    finally:
        hist_task.cancel()
        await market.stop()
        await client.shutdown()


app = FastAPI(
    title="craftflip",
    version=__version__,
    description=(
        "Real-time craft-flip finder for DonutSMP. Costs every vanilla crafting "
        "recipe against live donut.auction prices and ranks the profit."
    ),
    lifespan=lifespan,
)


def _require_ready() -> None:
    if state.get("recipes_error"):
        raise HTTPException(status_code=503, detail=state["recipes_error"])


# ---------------------------------------------------------------- health ----
@app.get("/health")
async def health() -> dict[str, Any]:
    market: Market | None = state.get("market")
    ok = bool(market and market.index)
    return {
        "status": "ok" if ok and not state.get("recipes_error") else "degraded",
        "version": __version__,
        "recipesLoaded": len(state.get("recipes") or []),
        "recipesError": state.get("recipes_error"),
        "indexSize": len(market.index) if market else 0,
    }


# ---------------------------------------------------------------- status ----
@app.get("/api/status")
async def status() -> dict[str, Any]:
    market: Market = state["market"]
    table: FlipTable = state["table"]
    history: FlipHistory = state["history"]
    return {
        "service": "craftflip",
        "version": __version__,
        "upstream": config.UPSTREAM_BASE,
        "source": {"site": "https://donut.auction", "upstream": config.UPSTREAM_BASE},
        "market": market.snapshot(),
        "table": table.stats(),
        "history": history.status(),
        "recipes": state.get("recipes_meta"),
        "recipesError": state.get("recipes_error"),
        "config": {
            "indexTtlSeconds": config.INDEX_TTL_SECONDS,
            "flipsTtlSeconds": config.FLIPS_TTL_SECONDS,
            "feePercent": config.DONUT_FEE_PERCENT,
            "requestSpacingSeconds": config.REQUEST_SPACING_SECONDS,
            "maxRequestsPerRefresh": config.MAX_REQUESTS_PER_REFRESH,
        },
    }


# ---------------------------------------------------------------- crafts ----
@app.get("/api/crafts")
async def crafts(
    q: str | None = None,
    minProfit: float | None = None,
    minMargin: float | None = None,
    sort: str = Query("profit", pattern="^(profit|margin|cost|revenue|item|profitPerUnit)$"),
    limit: int = Query(100, ge=1, le=500),
    profitableOnly: bool = True,
) -> dict[str, Any]:
    _require_ready()
    market: Market = state["market"]
    table: FlipTable = state["table"]
    await market.ensure_fresh()
    rows = await table.query(
        q=q,
        min_profit=minProfit,
        min_margin=minMargin,
        sort=sort,
        limit=limit,
        profitable_only=profitableOnly,
    )
    return {
        "count": len(rows),
        "items": rows,
        "meta": {
            **table.stats(),
            "indexAgeSeconds": None if market.age is None else round(market.age, 1),
            "upstreamOk": market.upstream_ok,
            "indexSize": len(market.index),
        },
    }


@app.get("/api/crafts/{item_name}/history")
async def craft_history(item_name: str, days: int = Query(14, ge=1, le=90)) -> dict[str, Any]:
    history: FlipHistory = state["history"]
    name = normalize_query(item_name)
    points = history.series(name, days)
    return {
        "item": name,
        "days": days,
        "points": points,
        "available": history.available,
        "note": None
        if points
        else (
            "No history recorded yet. Series build up as the index refreshes; "
            "a persistent volume must be mounted at DATA_DIR."
        ),
    }


@app.get("/api/crafts/{item_name}")
async def craft_detail(item_name: str) -> dict[str, Any]:
    _require_ready()
    name = normalize_query(item_name)
    market: Market = state["market"]
    table: FlipTable = state["table"]
    await market.ensure_fresh()

    flip = await table.find(name)
    recipe = next(
        (r for r in state["recipes"] if r["output"]["item"] == name), None
    )
    if flip is None and recipe is None:
        raise HTTPException(status_code=404, detail=f"no craftable recipe or price for {name!r}")

    out: dict[str, Any] = {
        "item": name,
        "displayName": prettify(name),
        "flip": flip,
        "craftable": recipe is not None,
    }
    if recipe is not None:
        out["grid"] = recipe_grid(recipe, market)
        out["recipeId"] = recipe["id"]
        out["recipeType"] = recipe["type"]
        if flip is None:
            out["unpriced"] = (
                "This recipe exists but at least one material has no price on "
                "donut.auction, so it cannot be costed."
            )

    # recent sales -- the one place that costs an upstream request
    entry = market.lookup(name)
    if entry and entry.get("itemId"):
        try:
            tx = await state["client"].transactions(entry["itemId"])
            out["recentSales"] = [
                {
                    "price": t.get("price"),
                    "itemCount": t.get("itemCount"),
                    "seller": t.get("seller") or t.get("sellerName"),
                    "at": t.get("createdAt") or t.get("at") or t.get("soldAt"),
                }
                for t in tx[:15]
            ]
        except UpstreamError as exc:
            out["recentSales"] = []
            out["recentSalesError"] = str(exc)
    return out


# ---------------------------------------------------------------- market ----
@app.get("/api/items/search")
async def items_search(q: str = "", limit: int = Query(25, ge=1, le=25)) -> dict[str, Any]:
    """Live passthrough to donut.auction search, ranked. Caps at 25 like upstream."""
    _require_ready()
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    try:
        ranked = await state["client"].resolve(q)
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "query": normalize_query(q),
        "count": len(ranked[:limit]),
        "items": [
            {
                "itemId": r["itemId"],
                "itemName": r["itemName"],
                "displayName": r["displayName"],
                "enchantments": r["enchantments"],
                "marketValue": (r["price"] or {}).get("value"),
            }
            for r in ranked[:limit]
        ],
    }


@app.get("/api/market/{item_name}")
async def market_item(item_name: str) -> dict[str, Any]:
    _require_ready()
    name = normalize_query(item_name)
    market: Market = state["market"]
    entry = market.lookup(name)
    if entry is None:
        await market.ensure_fresh()
        entry = market.lookup(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{name!r} is not priced in the current index")
    return {
        "item": name,
        "indexAgeSeconds": None if market.age is None else round(market.age, 1),
        **entry,
    }


# ------------------------------------------------------------------- SPA ----
_WEB = Path(config.WEB_DIST)


@app.get("/")
async def index() -> Any:
    if (_WEB / "index.html").exists():
        return FileResponse(_WEB / "index.html")
    return JSONResponse(
        status_code=503,
        content={
            "error": "frontend not built",
            "detail": f"no index.html at {_WEB}. Run the web build, or use the /docs API.",
            "api": "/docs",
        },
    )


@app.get("/{full_path:path}")
async def spa(full_path: str) -> Any:
    if full_path.startswith("api/") or full_path == "health":
        raise HTTPException(status_code=404, detail="not found")
    candidate = (_WEB / full_path).resolve()
    if _WEB.exists() and str(candidate).startswith(str(_WEB.resolve())) and candidate.is_file():
        return FileResponse(candidate)
    if (_WEB / "index.html").exists():
        return FileResponse(_WEB / "index.html")
    raise HTTPException(status_code=404, detail="not found")
