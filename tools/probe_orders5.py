"""api.donutsmp.net serves Swagger UI at /v1/ and /v2/. Find the spec URL and
list every documented endpoint, then check which ones cover buy orders.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request

CTX = ssl.create_default_context()
UA = {"User-Agent": "craftflip order probe", "Accept": "*/*"}


def get(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=timeout, context=CTX)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def spec_for(prefix: str) -> dict | None:
    st, html = get(f"https://api.donutsmp.net{prefix}")
    print(f"[{prefix}] swagger html {st} ({len(html)} bytes)")
    urls = re.findall(r"url:\s*[\"']([^\"']+)[\"']", html)
    urls += re.findall(r"[\"'](/[^\"']*\.json)[\"']", html)
    candidates = [u for u in urls]
    candidates += [f"{prefix}swagger.json", f"{prefix}openapi.json",
                   f"{prefix}swagger/v1/swagger.json", f"{prefix}swagger/v2/swagger.json",
                   f"{prefix}docs/swagger.json", "/swagger.json", "/openapi.json"]
    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        url = c if c.startswith("http") else "https://api.donutsmp.net" + (c if c.startswith("/") else prefix + c)
        st, body = get(url)
        if st == 200 and body.lstrip().startswith("{"):
            try:
                return json.loads(body)
            except Exception:  # noqa: BLE001
                pass
        print(f"    spec {st} {url}")
    return None


def describe(spec: dict, label: str) -> None:
    print(f"\n=== {label}: {spec.get('info', {}).get('title')} {spec.get('info', {}).get('version')} ===")
    print("servers:", spec.get("servers"))
    paths = spec.get("paths", {})
    print(f"{len(paths)} paths:")
    for p, ops in sorted(paths.items()):
        for verb, op in ops.items():
            if verb not in ("get", "post", "put", "delete"):
                continue
            params = ", ".join(
                f"{q.get('name')}{'*' if q.get('required') else ''}"
                for q in (op.get("parameters") or []) if isinstance(q, dict)
            )
            print(f"  {verb.upper():<5} {p:<52} {op.get('summary', '')[:44]}  [{params}]")
    orderish = [p for p in paths if re.search(r"order|bid|buy|sell|instant", p, re.I)]
    print(f"\n  >>> order/bid/buy/sell paths: {orderish}")


def main() -> None:
    for prefix in ("/v1/", "/v2/", "/"):
        spec = spec_for(prefix)
        if spec:
            describe(spec, prefix)
            break


if __name__ == "__main__":
    main()
