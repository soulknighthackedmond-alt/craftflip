"""The donut.auction order mirror is empty. Look for a buy side elsewhere:
api.donutsmp.net (official) plus the raw shape of the listing/ticker endpoints,
which may carry a buy/sell discriminator.
"""
from __future__ import annotations

import json
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "craftflip order probe", "Accept": "application/json"}


def get(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def main() -> None:
    print("=== api.donutsmp.net discovery ===")
    for path in ("/", "/docs", "/swagger", "/openapi.json", "/v1/", "/v2/", "/api",
                 "/v1/auction/list", "/v2/auction/list", "/v1/orders", "/v2/orders",
                 "/v1/auction/orders", "/v2/auction/orders", "/v1/order/list",
                 "/v2/auction/buyorders", "/v1/auction/requests"):
        st, body = get("https://api.donutsmp.net" + path)
        flag = "  <== " if st == 200 else "      "
        print(f"{flag}{st:>4} {path:<28} {body[:180].replace(chr(10), ' ')}")

    print("\n=== donut.auction tickers raw shape ===")
    st, body = get("https://api.donut.auction/v2/tickers/")
    print(f"  {st} ({len(body)} bytes)")
    try:
        d = json.loads(body)
        if isinstance(d, dict):
            print("  keys:", list(d))
            items = d.get("items") or d.get("tickers") or []
        else:
            items = d
        print(f"  count={len(items)}")
        if items:
            print("  first full:", json.dumps(items[0], indent=1)[:900])
            keys: set[str] = set()
            for it in items:
                keys.update(it.keys())
            print("  union of keys:", sorted(keys))
    except Exception as e:  # noqa: BLE001
        print("  parse fail", e, body[:200])

    print("\n=== any listing endpoint with a buy side? ===")
    for path in ("/v2/auctions/", "/v2/auctions/items/", "/v2/listings/", "/v2/items/",
                 "/v2/auctions/items/e5bce2cd-c5d1-42c2-9f3a-86f298c6ecff",
                 "/v2/items/e5bce2cd-c5d1-42c2-9f3a-86f298c6ecff",
                 "/v2/auctions/items/e5bce2cd-c5d1-42c2-9f3a-86f298c6ecff/prices"):
        st, body = get("https://api.donut.auction" + path)
        print(f"  {st:>4} {path:<62} {body[:220].replace(chr(10), ' ')}")


if __name__ == "__main__":
    main()
