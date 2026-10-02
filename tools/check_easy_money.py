"""End-to-end proof that a recorded order turns into easy money.

Run against an instance whose order book you are willing to write to -- point it at
a throwaway DATA_DIR, not the deployment:

  set DATA_DIR=%TEMP%\\cfcheck && python tools/check_easy_money.py http://127.0.0.1:8801

It picks a real craftable item that is buyable right now, records an order priced
above its materials cost, and checks the whole chain: the arithmetic on the item
page, the easy-money flag, the filter, and that forgetting the order takes it back
out again.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

UA = {"User-Agent": "craftflip-easy-money-check", "Accept": "application/json"}
FAILED: list[str] = []


def call(base: str, path: str, method: str = "GET", payload=None, want: int = 200):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={**UA, "Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=120)
        raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except Exception as exc:  # noqa: BLE001
        print(f"ERR {method} {path}: {type(exc).__name__}: {exc}")
        FAILED.append(f"{method} {path}")
        return None
    if status != want:
        FAILED.append(f"{method} {path} -> {status}, wanted {want}")
        print(f"BAD {status} {method} {path} {raw[:200]}")
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(label)


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8801"
    print(f"easy-money end-to-end against {base}\n")

    book = call(base, "/api/orders")
    check("order book starts empty", bool(book) and book["meta"]["book"]["orders"] == 0,
          f"orders={book['meta']['book']['orders'] if book else '?'}")
    check("order book is writable", bool(book) and book["meta"]["book"]["writable"])

    # a real item whose materials are all buyable right now, so easy money is
    # possible in principle
    rows = call(base, "/api/crafts?limit=500&profitableOnly=false")
    if not rows:
        print("no flip table; nothing to prove")
        return 1
    candidates = [r for r in rows["items"] if r["actionable"] and r["materialsTotal"] > 0]
    if not candidates:
        print("no actionable rows in this run; increase the request budget and retry")
        return 1
    target = candidates[0]
    item, cost = target["item"], target["cost"]
    per_craft = target["output"]["count"]
    print(f"     target {item}: cost {cost:,.0f}, {per_craft} per craft, "
          f"{target['materialsListed']}/{target['materialsTotal']} materials listed")

    check("it is not easy money before an order exists", target["easyMoney"] is False)
    check("it carries the order fields", "orderProfit" in target and target["orderProfit"] is None)

    # price the order 50% above the materials cost, so the arithmetic is unambiguous
    unit = round(cost / per_craft * 1.5, 2)
    quantity = per_craft * 3
    posted = call(base, "/api/orders", "POST",
                  {"item": item, "price": unit, "quantity": quantity, "buyer": "selfcheck"})
    if not posted:
        print("could not record an order; stopping")
        return 1
    flip = posted.get("flip") or {}
    expected_revenue = unit * per_craft
    expected_profit = expected_revenue - cost

    check("the order reads back as sent",
          posted["order"]["unitPrice"] == unit and posted["order"]["quantity"] == quantity)
    check("order revenue is the price times the recipe output",
          flip.get("orderRevenue") == expected_revenue,
          f"{flip.get('orderRevenue')} vs {expected_revenue}")
    check("order profit is revenue minus the materials",
          abs((flip.get("orderProfit") or 0) - expected_profit) < 0.01,
          f"{flip.get('orderProfit')} vs {expected_profit}")
    check("it absorbs the whole order", flip.get("orderFillable") == 3,
          f"fillable={flip.get('orderFillable')} (wanted {quantity}, {per_craft} per craft)")
    check("filling all of it pays three crafts' worth",
          abs((flip.get("orderTotalProfit") or 0) - expected_profit * 3) < 0.01,
          f"{flip.get('orderTotalProfit')}")
    check("it is now flagged easy money", flip.get("easyMoney") is True)

    # the flag has to reach the ledger, not just the detail view
    easy = call(base, "/api/crafts?easyMoneyOnly=true&limit=50")
    check("it appears in the easy-money filter",
          bool(easy) and any(r["item"] == item for r in easy["items"]),
          f"{easy['meta']['easyMoneyFound'] if easy else '?'} easy-money row(s)")

    book = call(base, "/api/orders?easyMoneyOnly=true")
    check("it appears on the order book",
          bool(book) and any(o["item"] == item for o in book["orders"]))
    check("the book reports it as easy money",
          bool(book) and book["meta"]["easyMoney"] >= 1)

    detail = call(base, f"/api/crafts/{item}")
    check("the item page carries the order", bool(detail) and detail.get("order") is not None)
    if detail:
        exit_info = detail.get("bestExit") or {}
        check("the best exit is the higher of order and /sell",
              exit_info.get("effective") == max(
                  [v for v in [exit_info.get("order"), exit_info.get("serverSell")] if v],
                  default=None,
              ),
              json.dumps(exit_info))

    # a stale order is shown but is never easy money
    stale = call(base, "/api/orders", "POST",
                 {"item": item, "price": unit, "quantity": quantity,
                  "seenAt": "2020-01-01T00:00:00Z"})
    if stale:
        check("an order nobody has re-checked is flagged stale",
              (stale.get("order") or {}).get("stale") is True)
        check("and a stale order is not easy money",
              (stale.get("flip") or {}).get("easyMoney") is False)

    # and forgetting it takes the flip back out
    call(base, f"/api/orders/{item}", "DELETE")
    after = call(base, f"/api/crafts/{item}")
    check("forgetting the order clears the flag",
          bool(after) and (after.get("flip") or {}).get("easyMoney") is False)
    gone = call(base, "/api/orders")
    check("and the book is empty again", bool(gone) and gone["meta"]["book"]["orders"] == 0)

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed:")
        for f in FAILED:
            print("  -", f)
        return 1
    print("all easy-money checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
