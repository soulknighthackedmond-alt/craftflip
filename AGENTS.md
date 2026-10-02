# craftflip — project notes

Real-time craft-flip finder for DonutSMP. FastAPI backend + React SPA, served by one
process, deployed to Coolify alongside the phase-1 `donut-auction-api`.

## Layout

- `app/donut.py` — upstream client for `api.donut.auction` (vendored from
  `donut-auction-api`, same query normalisation and TTL cache). Only the User-Agent
  differs.
- `app/market.py` — builds `name -> price`. Owns the index strategy.
- `app/flips.py` — recipe loading, the flip maths, the ranked table and the grid render.
- `app/history.py` — flip history as JSONL, degrades silently.
- `app/main.py` — API + SPA host. `web/` is Vite + React + TS, no UI kit.
- `tools/build_recipes.py` — generates `data/recipes.json` (committed).
- `tools/local_check.py` — one live index refresh + the resulting table, no server.
- `tools/verify_craftflip.py` — endpoint sweep against a running instance.

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
- There is **no public bid side**, so no real "instasell" quote exists. Order data is
  retired: donut.auction's `/orders` page says "Order data has been retired",
  `/v1/orders/items/{id}/prices` is 404, `/v2/orders/search/` returns `{"items":[]}`,
  and the official `api.donutsmp.net` has no order endpoint. The only sell-side data is
  `/v2/auctions/items/{id}/transactions` — max **10** rows and it does not paginate
  (`nextCursor` is null even when 10 come back).
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

