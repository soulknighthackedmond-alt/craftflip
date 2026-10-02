"""Endpoint sweep against a running craftflip.

  python tools/verify_craftflip.py http://192.168.50.60:8789

Exits non-zero if any check fails, so it is usable as a smoke test after a deploy.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "craftflip-verify/1.0", "Accept": "application/json"}
FAILED: list[str] = []


def call(base: str, path: str, want: int = 200, accept: str = "application/json"):
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, headers={**UA, "Accept": accept})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        body = r.read()
        status = r.status
    except urllib.error.HTTPError as e:
        body = e.read()
        status = e.code
    except Exception as exc:  # noqa: BLE001
        print(f"ERR {path:<46} {type(exc).__name__}: {exc}")
        FAILED.append(path)
        return None
    ok = status == want
    if not ok:
        FAILED.append(path)
    print(f"{'OK ' if ok else 'BAD'} {status} (want {want}) {path}")
    if accept == "application/json" and body[:1] in (b"{", b"["):
        try:
            return json.loads(body)
        except ValueError:
            return None
    return body


def body_call(base: str, path: str, method: str, payload=None, want: int = 200):
    """One request with a JSON body. Used for the order book's write endpoints."""
    url = base.rstrip("/") + path
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={**UA, "Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=60)
        raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except Exception as exc:  # noqa: BLE001
        print(f"ERR {method} {path:<46} {type(exc).__name__}: {exc}")
        FAILED.append(f"{method} {path}")
        return None
    ok = status == want
    if not ok:
        FAILED.append(f"{method} {path} -> {status}, wanted {want}")
    print(f"{'OK ' if ok else 'BAD'} {status} (want {want}) {method} {path}")
    if not ok:
        # a status we did not want is a failure to report, not a body to hand back
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def post(base: str, path: str, payload, want: int = 200):
    return body_call(base, path, "POST", payload, want)


def delete(base: str, path: str, want: int = 200):
    return body_call(base, path, "DELETE", None, want)


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8789"
    print(f"verifying {base}\n")

    health = call(base, "/health")
    if health:
        print(f"     health={health.get('status')} recipes={health.get('recipesLoaded')} "
              f"index={health.get('indexSize')}")

    status = call(base, "/api/status")
    if status:
        m = status.get("market", {})
        print(f"     index={m.get('indexSize')}/{m.get('needed')} "
              f"missing={m.get('missingCount')} age={m.get('ageSeconds')}s "
              f"upstreamOk={m.get('upstreamOk')} requests={m.get('requestsUsed')}")
        if m.get("lastError"):
            print(f"     lastError={m['lastError']}")
        if not m.get("indexSize"):
            FAILED.append("market index is empty")
        s = status.get("sales") or {}
        print(f"     salesIndex={s.get('priced')} tracked={s.get('tracked')} "
              f"basis={s.get('basis')!r} requests={s.get('requests')}")
        if s.get("lastError"):
            print(f"     sales lastError={s['lastError']}")
        sp = status.get("sellPrices") or {}
        print(f"     sellPrices={sp.get('items')} items multiplier={sp.get('multiplier')} "
              f"sources={sp.get('sources')} volumeCopy={sp.get('tableExists')}")
        if sp.get("errors"):
            print(f"     sell price table errors={sp['errors']}")
        if not sp.get("items"):
            FAILED.append("the /sell price table is empty")

    crafts = call(base, "/api/crafts?limit=5")
    top_item = None
    if crafts:
        print(f"     {crafts.get('count')} rows; meta={json.dumps(crafts.get('meta', {}))[:160]}")
        for row in crafts.get("items", [])[:5]:
            insta = row.get("instasellProfit")
            print(f"       {row['item']:<24} cost={row['cost']:>12,.0f} "
                  f"sale={row['revenue']:>12,.0f} profit={row['profit']:>12,.0f} "
                  f"margin={row['margin']*100:>7.1f}%"
                  f" instasell={'—' if insta is None else f'{insta:,.0f}'}"
                  f" conf={row.get('confidence')}%"
                  f"{'  est' if row['estimated'] else ''}")
        if crafts.get("items"):
            top_item = crafts["items"][0]["item"]
            first = crafts["items"][0]
            for field in ("instasellProfit", "confidence", "confidenceLabel", "dumpProfit"):
                if field not in first:
                    FAILED.append(f"/api/crafts rows are missing {field}")
            if not first.get("confidenceFactors"):
                FAILED.append("/api/crafts rows are missing the confidence breakdown")
            conf = first.get("confidence")
            if not isinstance(conf, int) or not 0 <= conf <= 100:
                FAILED.append(f"confidence out of range: {conf!r}")
        else:
            FAILED.append("/api/crafts returned no rows")

    # ranking by the sell-side number and by confidence both have to be accepted
    call(base, "/api/crafts?sort=instasellProfit&limit=3")
    call(base, "/api/crafts?sort=dumpProfit&limit=3")
    call(base, "/api/crafts?sort=confidence&limit=3")
    call(base, "/api/crafts?minConfidence=50&limit=3")
    call(base, "/api/crafts?minConfidence=101&limit=3", want=422)  # out of range
    call(base, "/api/crafts?sort=margin&limit=3")
    call(base, "/api/crafts?q=netherite&limit=5")
    call(base, "/api/crafts?minProfit=1000000&limit=3")
    call(base, "/api/items/search?q=netherite")
    call(base, "/api/items/search?q=", want=400)  # empty query is a client error
    call(base, "/api/market/netherite_ingot")
    call(base, "/api/crafts/zzz_not_a_real_item", want=404)

    if top_item:
        detail = call(base, f"/api/crafts/{top_item}")
        if detail:
            flip = detail.get("flip") or {}
            grid = detail.get("grid") or {}
            cells = grid.get("cells") or []
            slots = grid.get("slots") or []
            placed = sum(1 for r in cells for c in r if c) or len(slots)
            sales = detail.get("recentSales") or []
            summary = detail.get("salesSummary") or {}
            print(f"     detail {top_item}: craftable={detail.get('craftable')} "
                  f"type={detail.get('recipeType')} "
                  f"ingredients={len(flip.get('ingredients', []))} "
                  f"placedCells={placed} sales={len(sales)}")
            insta = flip.get("instasellProfit")
            print(f"       instasell={'—' if insta is None else format(insta, ',.0f')} "
                  f"basis={flip.get('instasellBasis')!r} "
                  f"dump={'—' if flip.get('dumpProfit') is None else format(flip['dumpProfit'], ',.0f')}")
            conf = flip.get("confidence")
            print(f"       confidence={conf}% ({flip.get('confidenceLabel')}) "
                  f"from {len(flip.get('confidenceFactors') or [])} factor(s)")
            sell = detail.get("sellPrice")
            print(f"       sellPrice={'none in the table' if not sell else sell}")
            if conf is None:
                FAILED.append(f"top item {top_item} has no confidence")
            if summary:
                print(f"       salesSummary: {summary.get('sales')} on record, "
                      f"low={summary.get('low')} median={summary.get('median')} "
                      f"high={summary.get('high')}")
            if not flip:
                FAILED.append(f"top item {top_item} has no flip on its detail page")
            if not placed:
                FAILED.append(f"{top_item} detail page rendered no priced cells")
            # regression: the feed nests seller as an object and stamps timeSold,
            # so a flat read left both columns blank
            blank = [s for s in sales if not s.get("seller") or not s.get("at")]
            if sales and len(blank) == len(sales):
                FAILED.append(f"{top_item} sales feed has no seller/time on any row")
        call(base, f"/api/crafts/{top_item}/history")

    # the plan's hand-check: netherite ingot is 4 scrap + 4 gold
    ni = call(base, "/api/crafts/netherite_ingot")
    if ni and ni.get("flip"):
        f = ni["flip"]
        print(f"     netherite_ingot via {f['recipeId']} "
              f"({f['recipeType']}, x{f['outputCount']}):")
        for ing in f["ingredients"]:
            print(f"       {ing['count']}x {ing['item']:<18} @ {ing['unitPrice']:>12,.0f} "
                  f"= {ing['subtotal']:>13,.0f}  ({ing['source']})")
        print(f"       cost {f['cost']:,.0f}  sells for {f['revenue']:,.0f}  "
              f"profit {f['profit']:,.0f}")
        if f.get("instasellProfit") is not None:
            print(f"       instasell at {f['instasellUnitPrice']:,.0f} x{f['outputCount']} "
                  f"= {f['instasellRevenue']:,.0f}  profit {f['instasellProfit']:,.0f}")
        else:
            print("       instasell: no fixed /sell price for this item")
        print(f"       confidence {f.get('confidence')}% ({f.get('confidenceLabel')})")
    else:
        print("     netherite_ingot: not costable in this run")

    # the order book: the instasell side /sell routes into. There is no public feed
    # for it, so these endpoints are the only way in and out.
    orders = call(base, "/api/orders?limit=20")
    if orders:
        meta = orders.get("meta", {})
        book = meta.get("book", {})
        print(f"     order book: {book.get('orders')} recorded "
              f"({book.get('fresh')} fresh, {book.get('stale')} stale, ttl {book.get('ttlHours')}h) "
              f"writable={book.get('writable')} easyMoney={meta.get('easyMoney')}")
        if book.get("errors"):
            print(f"     order book errors={book['errors']}")
            FAILED.append(f"order book reported errors: {book['errors']}")
        if not book.get("writable"):
            FAILED.append("the order book has no writable path, so orders cannot be recorded")
        for entry in orders.get("orders", [])[:5]:
            print(f"       {entry['item']:<28} order={entry['unitPrice']:>12,.0f} "
                  f"x{entry['quantity']:<5} cost={entry.get('cost')} "
                  f"profit={entry.get('orderProfit')} "
                  f"total={entry.get('orderTotalProfit')} "
                  f"easy={entry.get('easyMoney')}")
        # a recorded order must reach the flip table, or the two views disagree
        if orders.get("orders"):
            first = orders["orders"][0]
            if first.get("craftable") and "orderProfit" not in first:
                FAILED.append("a craftable order has no economics attached")

    call(base, "/api/orders?easyMoneyOnly=true")
    call(base, "/api/orders/zzz_not_a_real_item", want=404)
    call(base, "/api/crafts?ordersOnly=true&limit=5")
    call(base, "/api/crafts?easyMoneyOnly=true&limit=5")
    call(base, "/api/crafts?sort=orderProfit&limit=3")
    call(base, "/api/crafts?sort=orderTotalProfit&limit=3")
    call(base, "/api/crafts?sort=not_a_sort_key&limit=3", want=422)  # the sort set is closed

    # write round-trip on a deliberately synthetic item, so a real order can never be
    # overwritten by a smoke test, and remove it again
    probe = "zz_craftflip_selfcheck"
    posted = post(base, "/api/orders", {"item": probe, "price": 12345, "quantity": 7})
    if posted:
        got = posted.get("order") or {}
        if got.get("unitPrice") != 12345 or got.get("quantity") != 7:
            FAILED.append(f"the write round-trip did not come back as sent: {got}")
        else:
            print(f"     write round-trip ok: {got.get('item')} "
                  f"{got.get('unitPrice')} x{got.get('quantity')}")
        # and it must be readable back through the book
        reread = call(base, f"/api/orders/{probe}")
        if reread and (reread.get("order") or {}).get("quantity") != 7:
            FAILED.append("a recorded order did not read back with its quantity")
        call(base, f"/api/orders/{probe}", want=200)
        removed = delete(base, f"/api/orders/{probe}")
        if not removed or not removed.get("removed"):
            FAILED.append("the recorded order could not be removed again")
        call(base, f"/api/orders/{probe}", want=404)  # and it is really gone
        # a bad price must be refused rather than stored: the 422 is asserted by the
        # wanted status, and the real test is that nothing landed on the book
        post(base, "/api/orders", {"item": probe, "price": 0, "quantity": 1}, want=422)
        post(base, "/api/orders", {"item": probe, "quantity": 1}, want=422)  # no price at all
        post(base, "/api/orders", {"item": probe, "price": -5, "quantity": 1}, want=422)
        post(base, "/api/orders", {"item": probe, "price": 10, "quantity": 0}, want=422)
        call(base, f"/api/orders/{probe}", want=404)  # none of them created an order

    # the SPA
    html = call(base, "/", accept="text/html")
    if isinstance(html, bytes) and b"<div id=\"root\">" not in html:
        FAILED.append("/ did not serve the SPA shell")
    call(base, "/item/netherite_ingot", accept="text/html")  # client route falls back to index.html

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed:")
        for f in FAILED:
            print("  -", f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
