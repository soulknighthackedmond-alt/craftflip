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

    crafts = call(base, "/api/crafts?limit=5")
    top_item = None
    if crafts:
        print(f"     {crafts.get('count')} rows; meta={json.dumps(crafts.get('meta', {}))[:160]}")
        for row in crafts.get("items", [])[:5]:
            print(f"       {row['item']:<24} cost={row['cost']:>12,.0f} "
                  f"sale={row['revenue']:>12,.0f} profit={row['profit']:>12,.0f} "
                  f"margin={row['margin']*100:>7.1f}%{'  est' if row['estimated'] else ''}")
        if crafts.get("items"):
            top_item = crafts["items"][0]["item"]
        else:
            FAILED.append("/api/crafts returned no rows")

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
            print(f"     detail {top_item}: craftable={detail.get('craftable')} "
                  f"type={detail.get('recipeType')} "
                  f"ingredients={len(flip.get('ingredients', []))} "
                  f"placedCells={placed} sales={len(detail.get('recentSales') or [])}")
            if not flip:
                FAILED.append(f"top item {top_item} has no flip on its detail page")
            if not placed:
                FAILED.append(f"{top_item} detail page rendered no priced cells")
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
    else:
        print("     netherite_ingot: not costable in this run")

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
