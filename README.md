# craftflip

Real-time craft-flip finder for **DonutSMP** — the [sky.coflnet.com/crafts](https://sky.coflnet.com/crafts)
idea, but for DonutSMP's auction house instead of Hypixel's bazaar.

For every vanilla crafting recipe it costs the materials against live
`api.donut.auction` prices, values the output at market, and ranks the profit.

```
GET /api/crafts?sort=margin&limit=5
```

Live at **http://flips.192.168.50.60.sslip.io** (homelab).

---

## How it works

donut.auction is a SvelteKit front end, so there is no HTML to scrape — its own
client calls the public JSON API at `api.donut.auction`. This wraps those endpoints
behind one queryable surface.

### The market index

The awkward part: `/v2/items/search` is **substring-matched and hard-capped at 25
results with no pagination**, and `/v2/tickers/` returns only ~45 hot items. The
whole market cannot be enumerated. See [`PROBE.md`](PROBE.md) for the evidence.

So the index is built around what a crafting recipe actually needs, not the whole
catalogue:

1. **Tickers** — one request, live listing prices for the hottest items.
2. **Ingredients, greedy token sweep** — because matching is substring, one query
   covers every needed name containing it. `white`, `black`, `iron`, `ingot`,
   `stairs`, `trapdoor` each resolve dozens of names in a single request.
3. **Ingredients, per-name** — anything the sweep did not see gets its own query.
4. **Outputs** — the same two stages, but *only* for recipes whose every material
   is now priced. A recipe that cannot be costed never has its output queried.

A query is a *sample* of at most 25 of its matches, so a sweep is never assumed to
have returned everything. Coverage is tracked by returned `itemName`.

The index is rebuilt every `INDEX_TTL_SECONDS` (default 600) by a background task,
paced at one request per `REQUEST_SPACING_SECONDS`, and the last good index is kept
if upstream fails.

### The flip

```
cost    = Σ quantity × (cheapest live listing, else market value)
revenue = output market value × output count
profit  = revenue − cost − (revenue × DONUT_FEE_PERCENT / 100)
margin  = profit / cost
```

- **Tag ingredients** (`#minecraft:planks`) resolve to whichever member is cheapest
  to buy — not one arbitrary representative.
- A recipe is **skipped** if any material has no price at all, or the output has none.
- A material with no live listing falls back to market value and marks the row
  `estimated`. Such a row is a *hypothetical* flip: nobody is currently selling that
  material. Rows where every material has a live listing are marked `actionable`,
  and the ledger has a **buyable now** filter for exactly this.
- Several recipes produce the same item (a direct craft and a `from_block` variant).
  The table keeps one row per output — preferring an actionable recipe, then the
  higher profit — and counts the rest as `alternates`.

### The sell side (instasell)

```
instasell price   = lowest price the output has actually sold for recently
instasell revenue = instasell price × output count
instasell profit  = instasell revenue − cost − fee
```

The listing side above is priced off donut.auction's market-value index, which is a
*smoothed* figure: for thin items it can sit a long way from what the item really
changes hands for. `pink_bed`'s index read 39,890 while ten actual sales went through
at 250,000–800,000. The instasell column is the reality check — a row can show a
healthy listing profit and a *negative* instasell profit, which means the flip only
pays if a buyer turns up at the index price.

DonutSMP has **no public bid side**. donut.auction retired its order data (its
`/orders` page says "Order data has been retired", `/v1/orders/items/{id}/prices` is
404, and `/v2/orders/search/` returns an empty list), and the official
`api.donutsmp.net` exposes auction listings and transactions only. So the only
sell-side signal available is the completed-sales feed, and it costs one request per
item.

That is far too expensive to fold into the price refresh, so `SalesIndex`
(`app/sales.py`) fills on its own slower cycle: ~875 outputs at a 1s gap, an hour
TTL, about 0.25 requests/second. Until an item's turn comes round its instasell
figures are `null` and the ledger shows a dash.

### Recipe data

`tools/build_recipes.py` generates `data/recipes.json` from
[InventivetalentDev/minecraft-assets](https://github.com/InventivetalentDev/minecraft-assets)
at ref `1.21.11` — the version donut.auction serves. Two requests total
(`recipe/_all.json`, `tags/item/_all.json`). Only `crafting_shaped` and
`crafting_shapeless` are kept; smelting, stonecutting and smithing are dropped.

The Dockerfile generates it in its own build stage, so the dataset always matches
the pinned version.

---

## API

| Endpoint | What it gives you |
| --- | --- |
| `GET /api/crafts` | the ranked table; `sort=profit\|margin\|cost\|revenue\|item\|profitPerUnit\|instasellProfit` |
| `GET /api/crafts/{item}` | one item: recipe grid with priced slots, full arithmetic, and its recent sales |
| `GET /api/crafts/{item}/history` | craftflip's own recorded profit history for that flip |
| `GET /api/items/search?q=` | item name lookup |
| `GET /api/market/{item}` | the raw price index entry for an item |
| `GET /api/status` | index age, request counts, sales-index fill state |
| `GET /health` | liveness plus index sizes |

Every flip row carries `instasellProfit`, `instasellUnitPrice`, `instasellBasis` and
`instasellSales` alongside the listing-side `profit`. `instasellProfit` is `null`
until the sales index has looked that item up.

| endpoint | gives |
| --- | --- |
| `GET /api/crafts` | ranked table. `q`, `minProfit`, `minMargin`, `sort` (`profit`\|`margin`\|`cost`\|`revenue`\|`item`\|`profitPerUnit`\|`instasellProfit`), `limit`, `profitableOnly` |
| `GET /api/crafts/{item}` | one flip: recipe grid, per-ingredient breakdown, recent sales |
| `GET /api/crafts/{item}/history` | profit and margin over time (`days`) |
| `GET /api/items/search` | live passthrough to donut.auction search, ranked |
| `GET /api/market/{item}` | the raw index entry for one item |
| `GET /api/status` | index size, age, request count, upstream health, sales-index fill |
| `GET /health` | liveness |
| `GET /docs` | interactive OpenAPI docs |

`netherite_ingot`, `Netherite Ingot` and `minecraft:netherite_ingot` all resolve to
the same item.

---

## Running it

```bash
# the recipe dataset (writes data/recipes.json)
python tools/build_recipes.py

# engine tests -- no network, no pytest needed
python tests/test_flips.py

# one full index refresh against live upstream, prints the resulting table
python tools/local_check.py

# the whole service
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8789
```

The SPA is served by the same process:

```bash
cd web && npm install && npm run build   # -> web/dist, served at /
cd web && npm run dev                    # dev server on :5173, proxies the API
```

Docker:

```bash
docker compose up --build
```

After a deploy:

```bash
python tools/verify_craftflip.py http://192.168.50.60:8789
```

---

## Configuration

| env | default | meaning |
| --- | --- | --- |
| `PORT` | `8789` | HTTP port |
| `DONUT_API_BASE` | `https://api.donut.auction` | upstream |
| `INDEX_TTL_SECONDS` | `600` | how long an index stays usable |
| `FLIPS_TTL_SECONDS` | `30` | how long a computed table is served |
| `DONUT_FEE_PERCENT` | `0` | DonutSMP's cut on a completed sale |
| `REQUEST_SPACING_SECONDS` | `0.25` | gap between upstream requests |
| `MAX_REQUESTS_PER_REFRESH` | `1400` | ceiling on requests in one refresh |
| `DATA_DIR` | `<repo>/data` | flip history log |
| `HISTORY_TOP_N` | `200` | flips recorded per refresh |
| `HISTORY_RETENTION_DAYS` | `14` | history kept |

**`DONUT_FEE_PERCENT` is 0 until a real figure is supplied** — every profit here is
gross of any auction fee. Set it and the whole table adjusts.

---

## Flip history

Each index refresh appends the top `HISTORY_TOP_N` flips to
`DATA_DIR/flips-YYYY-MM-DD.jsonl`, one compact line per refresh. The item page draws
the series, so a flip shows whether it has been worth doing for days rather than for
one snapshot. If the volume is not mounted, history degrades silently to a single
point and the live table is unaffected.

---

## Design

A bill-of-materials ledger, not a dashboard. Ink canvas, hairline rules, one accent
colour (honey amber for profit, rust for loss) and nothing else coloured. Archivo
for UI with expanded caps column labels; JetBrains Mono with tabular figures and a
slashed zero for every number.

The signature element is that a row **unfolds in place** into the recipe: materials
and their unit costs on the left, the real craft grid in the middle, the arithmetic
on the right. A thin margin ruler per row makes profit scannable down the column.

No UI kit, no chart library, no gradients. Keyboard focus is visible, it works to
380px, and `prefers-reduced-motion` is respected.

---

## Credits

Price data belongs to [donut.auction](https://donut.auction); this reads their public
API and is not affiliated with them. Recipe data from
[InventivetalentDev/minecraft-assets](https://github.com/InventivetalentDev/minecraft-assets)
(vanilla Minecraft data). Minecraft is a trademark of Mojang.
