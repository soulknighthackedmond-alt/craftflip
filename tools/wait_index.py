"""Wait until the local craftflip has priced something, then report the index."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8796"
want = int(sys.argv[2]) if len(sys.argv) > 2 else 1
deadline = time.time() + 240

while time.time() < deadline:
    try:
        h = json.load(urllib.request.urlopen(base + "/health", timeout=15))
        if h.get("indexSize", 0) >= want:
            print(f"index ready: {h['indexSize']} items, sellPrices={h.get('sellPricesLoaded')}")
            sys.exit(0)
        print(f"  waiting: index={h.get('indexSize')} sales={h.get('salesIndexSize')}")
    except urllib.error.URLError as exc:
        print(f"  not up yet: {exc}")
    time.sleep(10)

print("timed out waiting for the index")
sys.exit(1)
