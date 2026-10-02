"""Probe donut.auction for the buy-order (instasell fill) endpoints.

The site retired its /orders page, but the SvelteKit bundle still ships an API
client that talks to order endpoints. This greps the live bundle for the exact
paths and then tests every candidate against the live API.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (craftflip order probe)", "Accept": "*/*"}


def fetch(url: str, timeout: int = 20) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
        return r.status, r.headers.get("content-type", ""), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, "", f"{type(e).__name__}: {e}"


def bundle_paths() -> list[str]:
    st, _, html = fetch("https://donut.auction/orders")
    print(f"[html] /orders -> {st} ({len(html)} bytes)")
    seeds = set(re.findall(r"/_app/immutable/[^\"'\s)]+\.js", html))
    seen: set[str] = set()
    out: list[str] = []
    queue = list(seeds)
    while queue and len(out) < 60:
        p = queue.pop(0)
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        st, _, body = fetch("https://donut.auction" + p, timeout=25)
        if st == 200:
            for m in re.findall(r"/_app/immutable/[^\"'\s)]+\.js", body):
                if m not in seen:
                    queue.append(m)
    return out


def main() -> None:
    paths = bundle_paths()
    print(f"[bundle] {len(paths)} chunks")

    hits: dict[str, set[str]] = {}
    for p in paths:
        st, _, body = fetch("https://donut.auction" + p, timeout=25)
        if st != 200:
            continue
        for m in re.findall(r"[\"'`](/v[12]/[a-z0-9/_{}.\-]*order[a-z0-9/_{}.\-]*)", body, re.I):
            hits.setdefault(m, set()).add(p)
        for m in re.findall(r"[\"'`](/v[12]/[a-z0-9/_{}.\-]*bid[a-z0-9/_{}.\-]*)", body, re.I):
            hits.setdefault(m, set()).add(p)
    print("\n[bundle] order/bid paths found in the client:")
    for path, where in sorted(hits.items()):
        print(f"  {path}   ({len(where)} chunk(s))")

    item = "e5bce2cd-c5d1-42c2-9f3a-86f298c6ecff"  # netherite_ingot
    candidates = sorted(hits) + [
        "/v2/orders/search/",
        "/v2/orders/",
        "/v2/orders",
        f"/v2/items/{item}/orders",
        f"/v2/auctions/items/{item}/orders",
        f"/v1/orders/items/{item}/prices",
        f"/v2/orders/items/{item}/prices",
    ]
    seen: set[str] = set()
    print("\n[live] probing candidates on api.donut.auction:")
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        for suffix in ("", "?sort=price", "?sort=pricePerUnit&limit=5"):
            st, ct, body = fetch("https://api.donut.auction" + path + suffix, timeout=20)
            snippet = body[:220].replace("\n", " ")
            print(f"  {st:>4} {path + suffix:<60} {snippet}")
            if st == 200 and body.strip() not in ("", "[]", '{"items":[]}'):
                try:
                    data = json.loads(body)
                    n = len(data) if isinstance(data, list) else len(data.get("items", [])) if isinstance(data, dict) else -1
                    print(f"       ^^ PARSED len={n} keys={list(data)[:10] if isinstance(data, dict) else 'list'}")
                except Exception:  # noqa: BLE001
                    pass


if __name__ == "__main__":
    main()
