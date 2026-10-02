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
from pydantic import BaseModel

from . import __version__, config
from .donut import DonutClient, UpstreamError, normalize_query, prettify, sale_row, summarise_sales
from .flips import FlipTable, RecipeDataError, load_recipes, recipe_grid
from .history import FlipHistory
from .market import Market
from .orders import OrderBook
from .sales import SalesIndex
from .sellprices import SellPrices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("craftflip")

state: dict[str, Any] = {}


async def _history_loop() -> None:
    """Record the top flips: once as soon as the first index exists, then once per
    refresh. Without the initial wait-then-write the first point would not land
    until a whole TTL had passed, so a fresh deploy showed an empty history."""
    market: Market = state["market"]
    table: FlipTable = state["table"]
    history: FlipHistory = state["history"]

    while market.built_at is None:
        await asyncio.sleep(5)

    while True:
        try:
            if market.built_at is not None:
                rows = await table.rows()
                history.append(rows, config.DONUT_FEE_PERCENT)
                history.prune()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("history loop: %s", exc)
        await asyncio.sleep(config.INDEX_TTL_SECONDS)


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
    sales = SalesIndex(
        ttl=config.SALES_TTL_SECONDS,
        spacing=config.SALES_SPACING_SECONDS,
        max_per_cycle=config.SALES_MAX_PER_CYCLE,
    )
    sell_prices = SellPrices(
        path=config.SELL_PRICES_PATH,
        seed_path=config.SELL_PRICES_SEED_PATH,
        multiplier=config.SELL_MULTIPLIER,
    )
    orders = OrderBook(
        path=config.ORDERS_PATH,
        seed_path=config.ORDERS_SEED_PATH,
        ttl_hours=config.ORDERS_TTL_HOURS,
    )
    table = FlipTable(
        market,
        doc["recipes"],
        config.DONUT_FEE_PERCENT,
        config.FLIPS_TTL_SECONDS,
        sales,
        sell_prices,
        orders,
    )
    history = FlipHistory(config.DATA_DIR, config.HISTORY_TOP_N, config.HISTORY_RETENTION_DAYS)

    state.update(
        {
            "client": client,
            "market": market,
            "table": table,
            "sales": sales,
            "history": history,
            "sell_prices": sell_prices,
            "orders": orders,
        }
    )
    await market.start()
    await sales.start(client, market)
    hist_task = asyncio.create_task(_history_loop(), name="flip-history")

    try:
        yield
    finally:
        hist_task.cancel()
        await sales.stop()
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
    sales: SalesIndex | None = state.get("sales")
    sell_prices: SellPrices | None = state.get("sell_prices")
    orders: OrderBook | None = state.get("orders")
    ok = bool(market and market.index)
    return {
        "status": "ok" if ok and not state.get("recipes_error") else "degraded",
        "version": __version__,
        "recipesLoaded": len(state.get("recipes") or []),
        "recipesError": state.get("recipes_error"),
        "indexSize": len(market.index) if market else 0,
        "salesIndexSize": sales.size() if sales else 0,
        "sellPricesLoaded": sell_prices.size() if sell_prices else 0,
        "ordersLoaded": orders.size() if orders else 0,
    }


# ---------------------------------------------------------------- status ----
@app.get("/api/status")
async def status() -> dict[str, Any]:
    market: Market = state["market"]
    table: FlipTable = state["table"]
    history: FlipHistory = state["history"]
    sales: SalesIndex = state["sales"]
    sell_prices: SellPrices = state["sell_prices"]
    orders: OrderBook = state["orders"]
    return {
        "service": "craftflip",
        "version": __version__,
        "upstream": config.UPSTREAM_BASE,
        "source": {"site": "https://donut.auction", "upstream": config.UPSTREAM_BASE},
        "market": market.snapshot(),
        "sales": sales.snapshot(),
        "sellPrices": sell_prices.snapshot(),
        "orders": orders.snapshot(),
        "table": table.stats(),
        "history": history.status(),
        "recipes": state.get("recipes_meta"),
        "recipesError": state.get("recipes_error"),
        "config": {
            "indexTtlSeconds": config.INDEX_TTL_SECONDS,
            "flipsTtlSeconds": config.FLIPS_TTL_SECONDS,
            "feePercent": config.DONUT_FEE_PERCENT,
            "sellMultiplier": config.SELL_MULTIPLIER,
            "ordersTtlHours": config.ORDERS_TTL_HOURS,
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
    minConfidence: int | None = Query(None, ge=0, le=100),
    sort: str = Query(
        "profit",
        pattern=(
            "^(profit|margin|cost|revenue|item|profitPerUnit|confidence|"
            "instasellProfit|dumpProfit|orderProfit|orderTotalProfit)$"
        ),
    ),
    limit: int = Query(100, ge=1, le=500),
    profitableOnly: bool = True,
    ordersOnly: bool = False,
    easyMoneyOnly: bool = False,
) -> dict[str, Any]:
    _require_ready()
    market: Market = state["market"]
    table: FlipTable = state["table"]
    await market.ensure_fresh()
    rows = await table.query(
        q=q,
        min_profit=minProfit,
        min_margin=minMargin,
        min_confidence=minConfidence,
        sort=sort,
        limit=limit,
        profitable_only=profitableOnly,
        orders_only=ordersOnly,
        easy_money_only=easyMoneyOnly,
    )
    return {
        "count": len(rows),
        "items": rows,
        "meta": {
            **table.stats(),
            "ordersRecorded": state["orders"].size(),
            "ordersTtlHours": config.ORDERS_TTL_HOURS,
            "indexAgeSeconds": None if market.age is None else round(market.age, 1),
            "upstreamOk": market.upstream_ok,
            "indexSize": len(market.index),
        },
    }


# ---------------------------------------------------------------- orders ----
class OrderIn(BaseModel):
    """One player buy order, as /orders shows it in game.

    `price` is what the buyer pays per item. Send `totalPrice` instead and it is
    divided by the quantity. `item` accepts the same loose spellings as every
    other endpoint: netherite_ingot, Netherite Ingot or minecraft:netherite_ingot.
    """

    item: str
    price: float | None = None
    totalPrice: float | None = None
    quantity: int = 1
    buyer: str | None = None
    note: str | None = None
    seenAt: str | None = None


@app.get("/api/orders")
async def list_orders(
    q: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    easyMoneyOnly: bool = False,
) -> dict[str, Any]:
    """The recorded order book, each order costed against its recipe.

    This is the answer to "which orders are easy money": for every order on the
    book, what the materials cost, what filling it pays, and how many crafts it
    absorbs. An order for an item with no vanilla recipe stays on the book but has
    no economics attached, rather than being hidden.
    """
    _require_ready()
    orders: OrderBook = state["orders"]
    table: FlipTable = state["table"]
    market: Market = state["market"]
    await market.ensure_fresh()
    rows = await table.rows()
    by_item = {r["item"]: r for r in rows}

    out: list[dict[str, Any]] = []
    for order in orders.all():
        flip = by_item.get(order["item"])
        entry: dict[str, Any] = {
            **order,
            "displayName": prettify(order["item"]),
            "craftable": flip is not None,
        }
        if flip is not None:
            entry.update(
                {
                    "cost": flip["cost"],
                    "craftablePerCraft": flip["output"]["count"],
                    "orderProfit": flip["orderProfit"],
                    "orderMargin": flip["orderMargin"],
                    "orderRevenue": flip["orderRevenue"],
                    "orderFillable": flip["orderFillable"],
                    "orderTotalProfit": flip["orderTotalProfit"],
                    "actionable": flip["actionable"],
                    "estimated": flip["estimated"],
                    "materialsListed": flip["materialsListed"],
                    "materialsTotal": flip["materialsTotal"],
                    "easyMoney": flip["easyMoney"],
                    "confidence": flip["confidence"],
                    "confidenceLabel": flip["confidenceLabel"],
                    "marketValue": flip["output"]["unitPrice"],
                    "dumpUnitPrice": flip["dumpUnitPrice"],
                    "instasellUnitPrice": flip["instasellUnitPrice"],
                    "profit": flip["profit"],
                    "margin": flip["margin"],
                }
            )
        out.append(entry)

    if q:
        needle = q.strip().lower().replace(" ", "_")
        out = [o for o in out if needle in o["item"]]
    if easyMoneyOnly:
        out = [o for o in out if o.get("easyMoney")]

    out.sort(
        key=lambda o: (
            o.get("orderTotalProfit") if o.get("orderTotalProfit") is not None else float("-inf")
        ),
        reverse=True,
    )
    return {
        "count": len(out),
        "orders": out[:limit],
        "meta": {
            "book": orders.snapshot(),
            "easyMoney": sum(1 for o in out if o.get("easyMoney")),
            "withEconomics": sum(1 for o in out if o["craftable"]),
            "indexAgeSeconds": None if market.age is None else round(market.age, 1),
            "feePercent": config.DONUT_FEE_PERCENT,
        },
    }


@app.post("/api/orders")
async def record_order(order: OrderIn) -> dict[str, Any]:
    """Record (or replace) the best known order for one item.

    Written to the mounted volume, so it survives a redeploy, and picked up by the
    flip table immediately -- no rebuild, no restart.
    """
    orders: OrderBook = state["orders"]
    price = order.price
    if price is None and order.totalPrice is not None:
        if order.quantity < 1:
            raise HTTPException(status_code=422, detail="quantity must be at least 1")
        price = order.totalPrice / order.quantity
    if price is None:
        raise HTTPException(status_code=422, detail="send price (per item) or totalPrice")
    try:
        saved = orders.put(
            order.item,
            price,
            quantity=order.quantity,
            buyer=order.buyer,
            note=order.note,
            seen_at=order.seenAt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    state["table"]._rows = None  # recompute so the new order shows up at once
    flip = await state["table"].find(saved["item"])
    return {
        "order": saved,
        "flip": flip,
        "meta": {"book": orders.snapshot(), "table": state["table"].stats()},
    }


@app.delete("/api/orders/{item_name}")
async def delete_order(item_name: str) -> dict[str, Any]:
    """Forget one item's order -- for when the buyer has taken it down."""
    orders: OrderBook = state["orders"]
    removed = orders.drop(normalize_query(item_name))
    if not removed:
        raise HTTPException(status_code=404, detail=f"no recorded order for {item_name!r}")
    state["table"]._rows = None
    return {"removed": True, "item": normalize_query(item_name), "meta": {"book": orders.snapshot()}}


@app.get("/api/orders/{item_name}")
async def order_detail(item_name: str) -> dict[str, Any]:
    """One recorded order with its full craft economics."""
    orders: OrderBook = state["orders"]
    name = normalize_query(item_name)
    order = orders.lookup(name)
    if order is None:
        raise HTTPException(status_code=404, detail=f"no recorded order for {name!r}")
    flip = await state["table"].find(name)
    return {"order": order, "flip": flip, "displayName": prettify(name)}


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
        # the fixed /sell price for this item, if one is in the table. Shown even for
        # items with no craftable recipe, since it stands on its own.
        "sellPrice": state["sell_prices"].lookup(name),
        # a recorded player buy order for this item, if any. /sell fills one when it
        # pays more than the base price, so this is the best exit when it exists.
        "order": state["orders"].lookup(name),
    }
    sell = out["sellPrice"]
    order = out["order"]
    out["bestExit"] = {
        "order": (order or {}).get("unitPrice"),
        "serverSell": (sell or {}).get("payout"),
        # what /sell actually pays: the higher of the two, since it routes to the
        # order when the order beats the server's own base price
        "effective": max(
            [v for v in [(order or {}).get("unitPrice"), (sell or {}).get("payout")] if v],
            default=None,
        ),
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
            sales = [sale_row(t) for t in tx[:15]]
            out["recentSales"] = sales
            out["salesSummary"] = summarise_sales(sales)
        except UpstreamError as exc:
            out["recentSales"] = []
            out["salesSummary"] = {"sales": 0, "priced": 0}
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

# The content type is set explicitly rather than guessed. Python's mimetypes reads
# the Windows registry, where .js is registered as text/plain, and a browser refuses
# to execute a module script served with a non-JS type -- so on a Windows host the
# SPA loaded and then silently did nothing. Linux gets .js right, which is why this
# only ever showed up locally.
_MEDIA_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain",
}


def _asset(path: Path) -> FileResponse:
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix.lower(), "text/html"))


@app.get("/")
async def index() -> Any:
    if (_WEB / "index.html").exists():
        return _asset(_WEB / "index.html")
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
        return _asset(candidate)
    if (_WEB / "index.html").exists():
        return _asset(_WEB / "index.html")
    raise HTTPException(status_code=404, detail="not found")
