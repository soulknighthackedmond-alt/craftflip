"""Decisive question: does /v2/orders/search/ ever return a non-empty list?

Substring-matched like the item search, so single letters should surface
everything if the book has anything in it at all.
"""
from __future__ import annotations

import json
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "craftflip order probe", "Accept": "application/json"}
BASE = "https://api.donut.auction"


def get(q: str) -> dict:
    req = urllib.request.Request(f"{BASE}/v2/orders/search/?query={q}", headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=25, context=CTX)
        return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"_status": e.code, "_body": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"_status": 0, "_body": f"{type(e).__name__}: {e}"}


def main() -> None:
    print("[single chars + digits]")
    for q in list("abcdefghijklmnopqrstuvwxyz") + list("0123456789"):
        d = get(q)
        n = len(d.get("orders", [])) if "orders" in d else -1
        if n:
            print(f"  {q!r} -> {n} orders")
            print("     first:", json.dumps(d["orders"][0])[:600])
        else:
            print(f"  {q!r} -> {n}")

    print("\n[common item tokens]")
    tokens = [
        "netherite", "diamond", "iron", "gold", "emerald", "shulker", "elytra", "beacon",
        "enchanted", "book", "sword", "pickaxe", "helmet", "chestplate", "leggings", "boots",
        "harness", "banner", "slab", "stairs", "log", "plank", "block", "ingot", "nugget",
        "potion", "apple", "totem", "trident", "mace", "spawner", "key", "crate", "voucher",
    ]
    for q in tokens:
        d = get(q)
        n = len(d.get("orders", [])) if "orders" in d else -1
        flag = "  <-- NON-EMPTY" if n and n > 0 else ""
        print(f"  {q:<14} -> {n}{flag}")
        if n and n > 0:
            print("     first:", json.dumps(d["orders"][0])[:700])


if __name__ == "__main__":
    main()
