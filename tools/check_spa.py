"""Is the built SPA actually being served, and does its bundle load?"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797"


def get(path):
    try:
        with urllib.request.urlopen(base + path, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]


s, html = get("/")
print("GET / ->", s, len(html), "bytes")
print(html[:600])
for src in re.findall(r"""<(?:script|link)[^>]+(?:src|href)=["']([^"']+)["']""", html):
    ss, body = get(src if src.startswith("/") else "/" + src)
    print(f"  {src} -> {ss} {len(body)} bytes")
    if src.endswith(".js") and ss == 200:
        for probe in ("confidence", "Instasell", "instasell", "conf.high"):
            print(f"      contains {probe!r}: {probe in body}")
