# craftflip — project notes

Real-time craft-flip finder for DonutSMP. FastAPI backend + React SPA, served by one
process, deployed to Coolify alongside the phase-1 `donut-auction-api`.

## Layout

- `app/donut.py` — upstream client for `api.donut.auction` (vendored from
  `donut-auction-api`, same query normalisation and TTL cache). Only the User-Agent
  differs.
- `app/market.py` — builds `name -> price`. Owns the index strategy.
- `app/flips.py` — recipe loading, the flip maths, the ranked table and the grid render.
- `app/sales.py` — the completed-sales index behind the market-dump column.
- `app/sellprices.py` — the fixed `/sell` price table, merged from the image copy and a
  volume copy, reloaded on mtime change.
- `app/confidence.py` — the per-row 0-100 confidence score and its factor breakdown.
- `app/history.py` — flip history as JSONL, degrades silently.
- `app/main.py` — API + SPA host. `web/` is Vite + React + TS, no UI kit.
- `data/sell_prices.json` — the committed `/sell` base prices (bare numbers allowed).
- `tools/build_recipes.py` — generates `data/recipes.json` (committed).
- `tools/local_check.py` — one live index refresh + the resulting table, no server.
- `tools/verify_craftflip.py` — endpoint sweep against a running instance.
- `tools/check_sell_side.py` — proves the `/sell` path and prints a full confidence breakdown.
- `tools/check_live_sell.py` — same check against a running instance: the seeded `/sell`
  payouts, the confidence score, and the SPA asset content-type.

## Build / test / run

- Tests: `python tests/test_flips.py` (plain asserts, **no pytest needed**).
  `python -m pytest tests -q` also works.
- Frontend: `cd web && npm run typecheck && npm run build` → `web/dist`.
  `vite build` does not typecheck; run `typecheck` separately.
- Local service: `uvicorn app.main:app --port 8789`.
- Deploy: `docker compose up --build`; the Dockerfile builds the SPA in a node stage
  and copies the committed `data/recipes.json` — no network needed at build time.

## Upstream constraints (do not re-litigate — see PROBE.md for evidence)

- `api.donut.auction/v2/items/search?q=` is **substring** matched, **hard-capped at
  25 results**, and `limit`/`offset`/`page`/`perPage` are all **ignored**. The market
  cannot be enumerated. Any index must be recipe-driven and must never assume a query
  returned everything it matches.
- `/v2/tickers/` is only ~45 hot items, not a snapshot.
- One `itemName` can appear with several `id`s — those are player-renamed items with
  a styled `displayName`. Always prefer the plain entry (`market.plain_entry`), or a
  cosmetic axe gets mistaken for the market price.
- `displayName` is null in practice; prettify `itemName` instead.
- There is **no public bid side**, so no real order-book "instasell" quote exists. Order
  data is retired: donut.auction's `/orders` page says "Order data has been retired",
  `/v1/orders/items/{id}/prices` is 404, `/v2/orders/search/` returns `{"items":[]}`,
  and the official `api.donutsmp.net` has no order endpoint. The last live order-book
  feed, `lootseller.io`, **retired on 2026-09-29** ("DonutSMP disabled its public API"),
  and `donutsmp.finance/api/items` is a **frozen 2026-06-25 snapshot** — its
  `/api/status` reports `running: false` and every order `t` is 2026-06-25T19:21Z, so
  its `instantSellPrice` is ~100 days stale and must not be used as live.
- The fixed `/sell` payout is `server base price × the player's own per-item multiplier`
  (1.0×–3.0×, raised via `/sellmulti`). `/sell` also auto-routes to the best matching
  order when one pays more, but orders are retired so there is nothing to compare.
  **Only 8 base prices are publicly confirmed** (donutsmp.wiki/sell): `oak_log` 300,
  `sand` 100, `diamond` 1200, `nether_gold_ore` 1200, `leather` 10000, `bamboo_block`
  500, `dried_kelp_block` 550, `ancient_debris` 1700000. A community quant project
  (`Aeripsen/donut-quant`) adds `spruce_slab` 12, `bone_meal` 30, `pink_petals` 10,
  `wildflowers` 10 — and disagrees on `dried_kelp_block` (300). There is no bulk source;
  the wiki's `/shop` prices are what the server *charges* and are **not** the `/sell`
  base. Values come from `/worth <item>` in game, via `data/sell_prices.json`.
- A transaction is `{seller:{uuid,name}, price, timeSold, itemId, itemCount}`. `price` is
  the total for that sale, so divide by `itemCount` for a unit price. Reading a flat
  `seller`/`createdAt` (as an earlier revision did) leaves both columns blank.
- The search `price` object is only `{value, volume24Hours, saleCount24Hours}`, and both
  24h fields are 0 in practice. `value` is a smoothed index, not a last-sale price, and
  it can be far off for thin items — `pink_bed`'s index read 39,890 while real sales
  went through at 250k–800k, so the instasell column can legitimately exceed the
  listing-side profit.

## Gotchas

- `data/recipes.json` is generated from `InventivetalentDev/minecraft-assets` ref
  `1.21.11`. `PrismarineJS/minecraft-data` is **not** usable for this: it collapses
  ingredient tags to one arbitrary member (`#minecraft:planks` → `acacia_planks`),
  which would misprice every recipe that uses a tag.
- Windows: `cmd.exe` has no `printf`/`head`/`tail`, and a newline inside a
  `python -c "..."` argument truncates it — keep `-c` scripts on one line.
- `DONUT_FEE_PERCENT` defaults to 0 and no real DonutSMP fee figure is known; every
  profit figure is gross of any auction cut.
- `instasell*` fields are the **fixed `/sell`** payout (server base × the player's own
  multiplier); the previous median-of-sales number moved to `dump*`. Do not conflate
  them: `/sell` needs no buyer, the dump does.
- Confidence (`app/confidence.py`) is a weighted blend — cost basis 34%, sell price 26%,
  agreement 16%, sales depth 12%, freshness 12% — and a row with any unlisted material
  is capped at 60% so an unexecutable flip can never read *high*. The cap appears as an
  extra `unbuyable` factor in the breakdown whenever `estimated` is true.
- **Windows serves the SPA as `text/plain` unless the media type is set explicitly**:
  Python's `mimetypes` reads the registry, where `.js` is registered as `text/plain`, and
  a browser refuses to execute a module script with a non-JS type — the page loads and
  then silently does nothing, with no console error. `app/main.py` sets the type from a
  `_MEDIA_TYPES` map rather than guessing. Linux gets `.js` right, so this only shows up
  when running locally on Windows.
- The sell-side (dump) price is the **median** of the recent sales, not the lowest:
  thin markets carry outlier dumps (`waxed_weathered_chiseled_copper` has one at 6,250
  against a 2.4M index) that would otherwise swing a whole item's number.
- That feed is **bimodal** for craftables: bulk stack sales clear at a much lower unit
  price than one-offs. `blue_stained_glass_pane` sells as 64-stacks at ~2–13k/unit and as
  singles at 78k–100k, so its median (~45k) sits between two prices that both really
  happen. `stone_slab` is the clean case — every sale is a 64-stack at ~2,187/unit and
  the index agrees at 2,169. Treat the instasell column as an estimate, not a quote.
- The flip table's cache compares `SalesIndex.revision`, not `last_pass`. `last_pass`
  stays `None` until a whole sales pass finishes, so a table built before any sales
  data existed looked permanently fresh and every instasell cell read `null`.

## Deployment (live as of 2026-10-02)

- GitHub: `https://github.com/soulknighthackedmond-alt/craftflip`, public, branch
  `master`. The requested org name `donutflip` is **permanently unavailable** — it is
  an existing personal user account, and GitHub shares one namespace between users and
  orgs, so no org can take that name. GitHub also has no API to create an org (UI
  only). Transferable to a real org later in one click.
- Coolify: project `craftflip` (`imj9vt172y7oinyorkrza0hd`), application `craftflip`
  (`f5gpz4htd346gclmagaa1d11`), server `localhost` = the panel box 192.168.50.60,
  `build_pack=dockerfile`, `ports_mappings=8789:8789`, domain
  `http://flips.192.168.50.60.sslip.io`. Panel: `http://192.168.50.60:8000/api/v1`.
- Deploy = push to `master` then `POST /deploy {"uuid": ...}`. Coolify clones from
  GitHub, so nothing can deploy before the branch exists.
- `POST /applications/public` returns a **null `fqdn`** even when `domains` was
  accepted; read the application back to get the real value. `POST /projects` returns
  only `{"uuid": ...}` with no `name` field.
- The `/sell` side is live and verified on the deployment: `/health` reports
  `sellPricesLoaded`, only 3 of the 12 seeded items are craftable recipe outputs
  (`bamboo_block`, `bone_meal`, and `diamond` via a recipe), so the fixed-payout
  instasell column is mostly dashes by design — an item with no known base price gets
  `null`, never a guess. Every row carries a confidence score (500/500 on the live
  table). The item endpoint nests the arithmetic under `flip`, not at the top level.

## Accuracy note (important when reading the table)

The ranked table is dominated by **estimated** rows. On a full-budget index
(988/1035 priced, 805 flips) only ~15 of 587 sampled rows had `actionable=true`
(every material backed by a live listing); the highest-profit rows — the waxed
copper blocks and hanging signs — are all `estimated=true`, costed from market value
because nobody is selling the input. Always check the `actionable` flag / the
**buyable now** filter (client-side, `web/src/pages/LedgerPage.tsx`) before treating a
margin as a real flip.
- `/api/crafts` has **no `offset`** and rejects `limit=1000` with 422 (max 500), so the
  full table cannot be paged from the API; union `sort=profit` and `sort=margin` to
  widen a sample.

