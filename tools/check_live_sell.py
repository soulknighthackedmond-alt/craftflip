"""Confirm the deployed /sell side: the fixed payout, the confidence score and the
SPA asset content-type. Read-only; run against any craftflip base URL.

    python tools/check_live_sell.py http://192.168.50.60:8789
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8789").rstrip("/")


def get(path: str, timeout: int = 120):
    return urllib.request.urlopen(BASE + path, timeout=timeout)


def main() -> int:
    print("base", BASE)

    health = json.load(get("/health", 90))
    print("health", health)

    # every item that has a seeded fixed /sell price
    for name in ("bamboo_block", "spruce_slab", "dried_kelp_block", "bone_meal"):
        try:
            d = json.load(get(f"/api/crafts/{name}", 120))
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            print(f"  {name}: {exc}")
            continue
        sell = d.get("sellPrice") or {}
        # the item endpoint nests the arithmetic under "flip"
        flip = d.get("flip") or {}
        print(
            f"  {name:<18} sell={sell.get('payout')} ({sell.get('source')})  "
            f"instasellProfit={flip.get('instasellProfit')}  "
            f"confidence={flip.get('confidence')}% ({flip.get('confidenceLabel')})"
        )

    # the ranked table: does any row carry a fixed-payout instasell profit?
    table = json.load(get("/api/crafts?limit=500&sort=instasellProfit", 180))
    items = table.get("items", [])
    seeded = [r for r in items if r.get("instasellProfit") is not None]
    print(f"rows={len(items)} with a fixed /sell payout={len(seeded)}")
    for r in sorted(seeded, key=lambda r: -(r.get("instasellProfit") or 0))[:6]:
        print(
            f"  {r['item']:<24} cost={r['cost']:>12,.0f} "
            f"instasell={r['instasellProfit']:>12,.0f} conf={r.get('confidence')}%"
        )

    # confidence is present on every row, and the filter works
    with_conf = [r for r in items if r.get("confidence") is not None]
    print(f"rows carrying a confidence score: {len(with_conf)}/{len(items)}")

    # SPA: the module script must be served with a JavaScript content-type
    html = get("/", 60).read().decode()
    title = re.search(r"<title>(.*?)</title>", html)
    print("title", title.group(1) if title else "none")
    assets = re.findall(r'src="(/assets/[^"]+\.js)"', html)
    print("js assets", assets)
    for asset in assets[:2]:
        r = get(asset, 60)
        body = r.read()
        print(f"  {asset} -> {r.headers.get('content-type')} ({len(body)} bytes)")
        if "javascript" not in (r.headers.get("content-type") or ""):
            print("    PROBLEM: a browser refuses to execute a module script with this type")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
