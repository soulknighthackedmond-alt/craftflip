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

## Gotchas

- `data/recipes.json` is generated from `InventivetalentDev/minecraft-assets` ref
  `1.21.11`. `PrismarineJS/minecraft-data` is **not** usable for this: it collapses
  ingredient tags to one arbitrary member (`#minecraft:planks` → `acacia_planks`),
  which would misprice every recipe that uses a tag.
- Windows: `cmd.exe` has no `printf`/`head`/`tail`, and a newline inside a
  `python -c "..."` argument truncates it — keep `-c` scripts on one line.
- `DONUT_FEE_PERCENT` defaults to 0 and no real DonutSMP fee figure is known; every
  profit figure is gross of any auction cut.
