# Upstream probe — api.donut.auction

Recorded 2026-10-02. Everything in craftflip reads this file; nothing downstream
re-litigates the data contract.

Probe method: direct read-only `GET`s against `https://api.donut.auction` with a
descriptive `User-Agent`. No HTML scraping — donut.auction is a SvelteKit front end
and these are the JSON endpoints its own client calls.

---

## 1. `GET /v2/tickers/`

**Result: 200, 0.86 s, 12 952 bytes, a JSON array of exactly 45 entries.**

It is **not** a full market snapshot. 45 entries is a curated "hottest items" list,
and there is no sign of a `limit` that raises it. This corrects the assumption the
plan was written on ("returns ALL live listings in one call").

Entry shape — all nine keys present on every entry:

| key | type | notes |
| --- | --- | --- |
| `itemId` | uuid string | stable item identity |
| `itemName` | string | snake_case, e.g. `netherite_helmet` |
| `displayName` | string \| null | **null in practice** — do not rely on it, prettify `itemName` instead |
| `enchantments` | array of `{name, level}` | empty for plain items |
| `quantity` | int | stack size of this listing |
| `listingPrice` | number | total price of the listing |
| `unitPrice` | number | per-item price — **this is the number to compare** |
| `observedAt` | ISO 8601 | when the snapshot saw it |
| `isStale` | bool | true once the listing has aged out |

Sample first entry: `netherite_helmet`, qty 1, unitPrice 5 700 000, observedAt
2026-10-02T15:10:03.344Z, isStale false.

**Consequence:** tickers is a cheap opportunistic source of live *listing* prices for
the hottest ~45 items, refreshed in one request. It cannot be the index.

## 2. `GET /v2/items/search?q=<string>`

**Matching is substring, not prefix** — this selects Branch A.

Evidence:

| `q` | count | returned names |
| --- | --- | --- |
| `` (empty) | 25 | `tnt`, `ice`, `map`, `mud`, `bow`, … |
| `a` | 25 | `map`, `lead`, `cake`, `rail`, `sand`, … |
| `e` | 25 | `ice`, `egg`, `lead`, `cake`, `vine`, … |
| `ingot` | 4 | `gold_ingot`, `iron_ingot`, `copper_ingot`, `netherite_ingot` |
| `netherite` | 19 | `netherite_axe` (×3, different enchant sets), `netherite_ingot`, … |
| `zzz` | 0 | — |

`a` and `e` matching names where the letter is in the *middle* (`map`, `lead`, `sand`)
proves substring rather than prefix. `ingot` matching only the four `*_ingot` items
confirms it is a literal substring test, not fuzzy.

**The result set is hard-capped at 25 entries per query.** `q=` (empty) returns 25,
not the whole catalogue. Empty query returns a default popular set rather than
everything.

Response shape (confirmed):

```
{ "items": [ { "item": { "id": <uuid>, "itemName": "netherite_ingot",
                         "enchantments": [] },
               "price": { "value": 4706927.7791,
                          "volume24Hours": 0,
                          "saleCount24Hours": 0 } }, … ] }
```

`price.value` is the market value in donut coins — the sale-side number. Note that
one `itemName` can appear several times with different `enchantments`; those are
distinct tradeable variants with distinct `id`s.

### Pagination: there is none

Verified by direct comparison — `q=` with each of these returns **the same 25
entries in the same order**, byte-for-byte:

| request | result |
| --- | --- |
| `?q=&limit=1000` | 25 items (tnt, ice, map, mud, …) |
| `?q=&limit=100` | identical 25 |
| `?q=&page=2` | identical 25 — page 1 again |
| `?q=&offset=25` | identical 25 — offset ignored |
| `?q=&perPage=100` | identical 25 |

`?q=netherite&limit=100` returns 19 — its true match count — so `limit` is not
being clamped, it is simply ignored. `page`/`offset`/`perPage` are ignored too:
there is no way to reach past the 25th result of any query.

Also confirmed 404 (do not use): `/v2/`, `/v2/items/`, `/v2/items?limit=1000`.
Only `/v2/items/search` and `/v2/items/{uuid}` address items.

**Consequence:** a query is a *sample* of at most 25 of its matches, so the index
must never assume a query returned everything that matches it. Coverage is tracked
by returned `itemName`, and anything not seen falls through to a narrower query.

### Display names and variants

One `itemName` can appear several times with different `id`s — these are
player-customised items. Example from `q=netherite`: two `netherite_axe` entries,
ids `270a94bf…` and `536074d9…`, both carrying a styled `displayName` and priced
5 593 000 vs 8 330 731. A plain item is one with empty `enchantments` and no
`displayName`; the index keeps only those, so a renamed cosmetic axe cannot be
mistaken for the real market price.

DonutSMP also carries items vanilla does not (`netherite_spear`,
`netherite_nautilus_armor`); the recipe set is vanilla, so they only ever appear as
ingredients if a vanilla recipe calls for them, which none do.

## 3. Other endpoints (carried over from the phase-1 client, still valid)

| endpoint | gives |
| --- | --- |
| `GET /v2/items/{itemId}` | item metadata by uuid |
| `GET /v2/auctions/items/{itemId}/prices?period=1d\|7d\|30d\|all` | price history buckets |
| `GET /v2/auctions/items/{itemId}/transactions` | recent completed sales |

---

## Index strategy chosen

Because search is substring but capped at 25, and tickers covers only 45 items:

1. **Recipe-driven, not market-driven.** craftflip only ever needs prices for item
   names that appear in a vanilla crafting recipe. The candidate set is fixed and
   known up front (from `data/recipes.json`), so the index is built by looking up
   those names — roughly a few hundred, not "the whole market".
2. **Name lookups, ranked.** For each needed name, `GET /v2/items/search?q=<name>`
   and keep the exact-`itemName` match, falling back to the best-ranked match. This
   reuses the phase-1 scorer.
3. **Tickers first, one free call.** `/v2/tickers/` seeds live listing prices for the
   hot items at no cost; anything it covers needs no listing lookup.
4. **Greedy token sweep before per-name fallback.** Since matching is substring, one
   query covers every needed name containing that substring. Group the needed names
   by shared token, query the tokens that cover the most names first, and drop what
   is already covered. Only names still uncovered get their own request. This keeps a
   full refresh well under one request per item.
5. **Paced and cached.** Requests spaced 250 ms behind a single-flight lock, index
   cached for `INDEX_TTL_SECONDS` (default 300), last good index retained on upstream
   error with `upstreamOk=false` rather than emptying the table.

The 25-cap means a query is never assumed to have returned everything it could match;
coverage is tracked explicitly and anything missing falls through to the next stage.
