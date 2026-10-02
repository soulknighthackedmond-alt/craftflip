"""Prove the /sell side end to end: the seeded items must show a real payout.

Also shows why the top of the profit table carries a low confidence -- those rows
have no listed materials, no sales and no fixed sell price, which is the whole
point of the score.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8796"
SEEDED = ["spruce_slab", "dried_kelp_block", "bone_meal", "bamboo_block", "oak_log", "diamond"]


def get(path):
    try:
        return json.load(urllib.request.urlopen(base + path, timeout=60))
    except urllib.error.HTTPError as e:
        return {"__status": e.code}


print("=== seeded /sell items, as the API reports them ===")
for name in SEEDED:
    d = get(f"/api/crafts/{name}")
    flip = d.get("flip") or {}
    sell = d.get("sellPrice")
    insta = flip.get("instasellProfit")
    line = f"  {name:<20}"
    if sell:
        line += f" /sell {sell['payout']:>12,.0f} ({sell['source']:<9})"
    else:
        line += f" {'no /sell price':>26}"
    if insta is not None:
        line += (f"  cost {flip['cost']:>10,.0f}  profit {insta:>11,.0f}"
                 f"  conf {flip['confidence']}%")
    elif d.get("craftable") is False:
        line += "  (not craftable, so no flip row)"
    else:
        line += "  (craftable but not costed in this partial index)"
    print(line)

print("\n=== a /sell row's full breakdown ===")
d = get("/api/crafts/spruce_slab")
flip = d.get("flip")
if flip:
    print(f"  {flip['item']}: cost {flip['cost']:,.0f} -> /sell {flip['instasellRevenue']:,.0f} "
          f"= {flip['instasellProfit']:,.0f} ({flip['instasellMargin']*100:,.1f}%)")
    print(f"  base {flip['instasellBasePrice']} x {flip['instasellMultiplier']}x "
          f"from {flip['instasellSource']}")
    for f in flip["confidenceFactors"]:
        print(f"    {f['label']:<16} {f['score']*100:>5.0f}% of {f['weight']*100:>4.0f}%"
              f" = {f['contribution']:>5} pts   {f['detail']}")
    print(f"  total {flip['confidence']}% ({flip['confidenceLabel']})")
else:
    print("  spruce_slab is not costed in this partial index")

print("\n=== highest-confidence rows (minConfidence=40) ===")
c = get("/api/crafts?minConfidence=40&limit=8&sort=confidence")
print(f"  {c.get('count')} row(s)")
for r in c.get("items", []):
    insta = r["instasellProfit"]
    print(f"    {r['item']:<26} conf {r['confidence']:>3}%  profit {r['profit']:>12,.0f}"
          f"  instasell {'—' if insta is None else format(insta, ',.0f')}"
          f"  listed {r['materialsListed']}/{r['materialsTotal']}")
