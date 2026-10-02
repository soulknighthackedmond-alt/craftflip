"""Does an empty order book bump its revision on every read?

`OrderBook.reload` guards with `if stamps == self._stamps and self._orders` -- and an
empty book makes `self._orders` falsy, so the guard never holds, the book re-reads and
bumps `revision` on every call. `FlipTable._is_fresh` compares against that revision, so
the flip table would rebuild on every request and `computedAt` would never settle.

This hits /api/status repeatedly and reports whether revision and computedAt move.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

base = (sys.argv[1] if len(sys.argv) > 1 else "http://192.168.50.60:8789").rstrip("/")
seen = []
for _ in range(4):
    d = json.load(urllib.request.urlopen(f"{base}/api/status", timeout=90))
    seen.append((d["orders"]["revision"], d["table"]["computedAt"], d["orders"]["orders"]))
    time.sleep(2)

for rev, at, n in seen:
    print(f"revision={rev:<8} computedAt={at}  orders={n}")

revs = [r for r, _, _ in seen]
ats = {a for _, a, _ in seen}
print()
if len(set(revs)) == 1 and len(ats) == 1:
    print("stable: revision and computedAt held across 4 calls")
    sys.exit(0)
if len(set(revs)) > 1:
    print(f"BUG: revision moved {revs} across 4 calls with {seen[0][2]} orders on the book")
if len(ats) > 1:
    print(f"BUG: computedAt moved {sorted(ats)} — the flip table is rebuilding every request")
sys.exit(1)
