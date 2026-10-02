"""/v2/orders/search/ requires a query and validates sort against a fixed set.
Find the accepted sort values, then read the real response shape.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "craftflip order probe", "Accept": "application/json"}
BASE = "https://api.donut.auction"


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=25, context=CTX)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def valid_sorts() -> list[str]:
    """Probe sort candidates; the validator names the allowed values when it rejects."""
    candidates = [
        "price", "pricePerUnit", "unitPrice", "createdAt", "timeCreated", "quantity",
        "totalPrice", "itemName", "priceAsc", "priceDesc", "recent", "newest", "cheapest",
        "expiresAt", "timeExpires", "amount",
    ]
    found: list[str] = []
    for s in candidates:
        st, body = fetch(f"{BASE}/v2/orders/search/?query=netherite&sort={s}&limit=5")
        if st == 200:
            found.append(s)
            print(f"  OK    sort={s}")
        elif "is not valid" in body:
            m = re.search(r"The value '.*?' is not valid\.(?: (.*?))?\"", body)
            # ASP.NET sometimes lists the allowed values in the message
            allowed = re.search(r"Allowed values?[:\s]+([^\"\]]+)", body)
            print(f"  400   sort={s}" + (f"  allowed={allowed.group(1)}" if allowed else ""))
        else:
            print(f"  {st:>4} sort={s}  {body[:120]}")
    return found


def main() -> None:
    print("[sorts]")
    ok = valid_sorts()

    print("\n[response shape]")
    for q in ("netherite_ingot", "netherite", "diamond", "iron"):
        st, body = fetch(f"{BASE}/v2/orders/search/?query={q}")
        print(f"  query={q} -> {st}")
        try:
            d = json.loads(body)
        except Exception:  # noqa: BLE001
            print(f"    {body[:300]}")
            continue
        if isinstance(d, dict):
            print(f"    keys={list(d)}")
            items = d.get("items") or d.get("results") or []
        else:
            items = d
        print(f"    items={len(items)}")
        if items:
            print("    first:", json.dumps(items[0])[:700])

    print("\n[query param variants]")
    for suffix in ("?query=netherite_ingot&limit=5", "?query=netherite_ingot&page=1&limit=5",
                   "?query=netherite_ingot&offset=0&limit=5", "?q=netherite_ingot"):
        st, body = fetch(f"{BASE}/v2/orders/search/{suffix}")
        try:
            d = json.loads(body)
            n = len(d.get("items", [])) if isinstance(d, dict) else len(d)
            print(f"  {st} {suffix:<48} items={n} {json.dumps(d)[:200]}")
        except Exception:  # noqa: BLE001
            print(f"  {st} {suffix:<48} {body[:160]}")


if __name__ == "__main__":
    main()
