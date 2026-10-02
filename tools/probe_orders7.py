"""Check whether the official API's v2 surface adds an order/bid endpoint the
v1 spec lacks.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "craftflip order probe", "Accept": "*/*"}


def get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=20, context=CTX)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


for candidate in ("https://api.donutsmp.net/v2/doc.json",
                  "https://api.donutsmp.net/doc.json",
                  "https://api.donutsmp.net/v2/swagger.json"):
    st, body = get(candidate)
    print(f"{st} {candidate} ({len(body)} bytes)")
    if st == 200 and body.lstrip().startswith("{"):
        d = json.loads(body)
        paths = d.get("paths", {})
        print("  basePath:", d.get("basePath"), "host:", d.get("host"))
        print(f"  {len(paths)} paths:")
        for p in sorted(paths):
            print("   ", p)
        print("  definitions:", sorted(d.get("definitions", {})))
        orderish = [p for p in paths if re.search(r"order|bid|buy|request", p, re.I)]
        print("  >>> ORDER-ISH:", orderish)
        break
